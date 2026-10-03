class SecurityError(Exception):
    pass

class PolicyEngine:
    def __init__(self):
        self.policies = {}
    
    def add_policy(self, bucket: str, name: str, action: str, condition_ast):
        if bucket not in self.policies:
            self.policies[bucket] = {'read': [], 'write': [], 'all': []}
        
        if action not in self.policies[bucket]:
            self.policies[bucket][action] = []
            
        self.policies[bucket][action].append({
            'name': name,
            'condition': condition_ast
        })
        
    def _evaluate_condition(self, condition_tokens, document: dict, context: dict, engine=None) -> bool:
        if not condition_tokens:
            return True
            
        expr_str = " ".join([t.lexeme for t in condition_tokens])
        import re
        
        # DSL Role Traversal: "my role = "admin""
        role_match = re.search(r'my role\s*(is not|is|!=|==|=)\s*"?([a-zA-Z0-9_]+)"?', expr_str, re.IGNORECASE)
        if role_match:
            op = role_match.group(1)
            target_role = role_match.group(2)
            user_role = context.get("role", "viewer")
            if op.lower() in ("=", "==", "is"):
                return user_role == target_role
            elif op.lower() in ("!=", "is not"):
                return user_role != target_role
                
        # DSL Bond Traversal: "bonded as \"owner\" to my user_id"
        bond_match = re.search(r'bonded as "?([a-zA-Z0-9_]+)"? to my ([a-zA-Z_]+)', expr_str)
        if bond_match and engine:
            label = bond_match.group(1)
            ctx_key = bond_match.group(2)
            user_id = context.get(ctx_key)
            doc_id = document.get("id") or document.get("_id") or document.get("gid", "")
            
            # Scan bonds
            bonds_data = engine.scan_bucket("_bonds")
            if bonds_data:
                import json
                bonds = json.loads(bonds_data)
                for b_doc in bonds:
                    b = b_doc.get("body", {})
                    # Is doc linked to user_id?
                    if b.get("label") == label:
                        if b.get("target") == doc_id and b.get("source") == user_id: return True
                        if b.get("target") == user_id and b.get("source") == doc_id: return True
            return False
            
        m1 = re.match(r'^([a-zA-Z_]+)(==|!=|isnot|is)@([a-zA-Z_]+)$', "".join([t.lexeme for t in condition_tokens]).lower())
        if m1:
            field = m1.group(1)
            op = m1.group(2)
            ctx_key = m1.group(3)
            body = document.get("body", document)
            val1 = body.get(field)
            val2 = context.get(ctx_key)
            if op in ('==', 'is'): return str(val1).lower() == str(val2).lower()
            if op in ('!=', 'isnot'): return str(val1).lower() != str(val2).lower()
            
        m2 = re.match(r'^@([a-zA-Z_]+)(==|!=|isnot|is)"?([a-zA-Z0-9_]+)"?$', "".join([t.lexeme for t in condition_tokens]).lower())
        if m2:
            ctx_key = m2.group(1)
            op = m2.group(2)
            val1 = context.get(ctx_key)
            val2 = m2.group(3)
            if op in ('==', 'is'): return str(val1).lower() == str(val2).lower()
            if op in ('!=', 'isnot'): return str(val1).lower() != str(val2).lower()
            
        # Generic Field Comparison: age > 18
        m3 = re.match(r'^([a-zA-Z_]+)(==|!=|isnot|is|>|<|>=|<=)"?([a-zA-Z0-9_\.]+)"?$', "".join([t.lexeme for t in condition_tokens]).lower())
        if m3:
            field = m3.group(1)
            op = m3.group(2)
            val2 = m3.group(3)
            
            body = document.get("body", document)
            val1 = body.get(field)
            
            if val1 is None: return False
            
            # Try numeric
            try:
                v1 = float(val1)
                v2 = float(val2)
            except ValueError:
                v1 = str(val1).lower()
                v2 = str(val2).lower()
                
            if op in ('==', 'is'): return v1 == v2
            if op in ('!=', 'isnot'): return v1 != v2
            if op == '>': return v1 > v2
            if op == '<': return v1 < v2
            if op == '>=': return v1 >= v2
            if op == '<=': return v1 <= v2
            
        return False


    def add_mask(self, bucket: str, field: str, condition_ast):
        if not hasattr(self, 'masks'):
            self.masks = {}
        if bucket not in self.masks:
            self.masks[bucket] = []
        self.masks[bucket].append({
            'field': field,
            'condition': condition_ast
        })

    def apply_masks(self, bucket: str, document: dict, context: dict, engine=None) -> dict:
        if str(context.get("bypass_dls", "false")).lower() == "true":
            return document
        if not hasattr(self, 'masks') or bucket not in self.masks:
            return document
            
        import copy
        masked_doc = copy.deepcopy(document)
        for mask in self.masks[bucket]:
            # If the condition evaluates to True, we APPLY the mask (redact it)
            if self._evaluate_condition(mask['condition'], masked_doc, context, engine):
                field = mask['field']
                if field in masked_doc:
                    del masked_doc[field]
        return masked_doc

    def check_read(self, bucket: str, document: dict, context: dict, engine=None) -> bool:

        if bucket not in self.policies:
            return True
            
        policies = self.policies[bucket].get('read', []) + self.policies[bucket].get('all', [])
        if not policies:
            return True
            
        # DLS standard: grant access if ANY policy passes
        for policy in policies:
            if self._evaluate_condition(policy['condition'], document, context, engine):
                return True
        return False
        
    def check_write(self, bucket: str, document: dict, context: dict) -> bool:
        if bucket not in self.policies:
            return True
            
        policies = self.policies[bucket].get('write', []) + self.policies[bucket].get('all', [])
        if not policies:
            return True
            
        # DLS standard: grant access if ANY policy passes
        for policy in policies:
            if self._evaluate_condition(policy['condition'], document, context):
                return True
        return False







MAX_FORECAST_HORIZON = 10000


def validate_webhook_url(url: str) -> str:
    """Reject webhook targets that could be abused for SSRF / local file access.

    Allowed: http/https only. Blocked: other schemes (file://, ftp://, ...),
    missing hosts, and link-local / cloud-metadata addresses (169.254.0.0/16, fe80::/10).
    Loopback and private LAN targets remain allowed (needed for local services).
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    if not isinstance(url, str) or not url:
        raise SecurityError("Webhook URL is required.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SecurityError("Webhook URL must use http or https.")
    host = parsed.hostname
    if not host:
        raise SecurityError("Webhook URL has no host.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return url  # unresolved now; re-validated again at delivery time
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_link_local:
            raise SecurityError("Webhook URL resolves to a blocked link-local/metadata address.")
    return url
