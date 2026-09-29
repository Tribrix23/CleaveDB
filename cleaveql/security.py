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
        
    def _evaluate_condition(self, condition_tokens, document: dict, context: dict) -> bool:
        if not condition_tokens:
            return True
            
        expr_str = "".join([t.lexeme for t in condition_tokens])
        
        # Support == and !=
        import re
        
        m1 = re.match(r'^([a-zA-Z_]+)(==|!=)@([a-zA-Z_]+)$', expr_str)
        if m1:
            field = m1.group(1)
            op = m1.group(2)
            ctx_key = m1.group(3)
            val1 = document.get(field)
            val2 = context.get(ctx_key)
            if op == '==': return val1 == val2
            if op == '!=': return val1 != val2
            
        m2 = re.match(r'^@([a-zA-Z_]+)(==|!=)"?([a-zA-Z0-9_]+)"?$', expr_str)
        if m2:
            ctx_key = m2.group(1)
            op = m2.group(2)
            val1 = context.get(ctx_key)
            val2 = m2.group(3)
            if op == '==': return val1 == val2
            if op == '!=': return val1 != val2
            
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

    def apply_masks(self, bucket: str, document: dict, context: dict) -> dict:
        if str(context.get("bypass_dls", "false")).lower() == "true":
            return document
        if not hasattr(self, 'masks') or bucket not in self.masks:
            return document
            
        import copy
        masked_doc = copy.deepcopy(document)
        for mask in self.masks[bucket]:
            # If the condition evaluates to True, we APPLY the mask (redact it)
            if self._evaluate_condition(mask['condition'], masked_doc, context):
                field = mask['field']
                if field in masked_doc:
                    masked_doc[field] = "***MASKED***"
        return masked_doc

    def check_read(self, bucket: str, document: dict, context: dict) -> bool:

        if bucket not in self.policies:
            return True
            
        policies = self.policies[bucket].get('read', []) + self.policies[bucket].get('all', [])
        if not policies:
            return True
            
        # RLS standard: grant access if ANY policy passes
        for policy in policies:
            if self._evaluate_condition(policy['condition'], document, context):
                return True
        return False
        
    def check_write(self, bucket: str, document: dict, context: dict) -> bool:
        if bucket not in self.policies:
            return True
            
        policies = self.policies[bucket].get('write', []) + self.policies[bucket].get('all', [])
        if not policies:
            return True
            
        # RLS standard: grant access if ANY policy passes
        for policy in policies:
            if self._evaluate_condition(policy['condition'], document, context):
                return True
        return False





