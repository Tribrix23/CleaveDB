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
        import re
        
        # Match pattern 1: field == @context
        m1 = re.match(r'^([a-zA-Z_]+)==@([a-zA-Z_]+)$', expr_str)
        if m1:
            field = m1.group(1)
            ctx_key = m1.group(2)
            return document.get(field) == context.get(ctx_key)
            
        # Match pattern 2: @context == "value"
        m2 = re.match(r'^@([a-zA-Z_]+)==\"?([a-zA-Z0-9_]+)\"?$', expr_str)
        if m2:
            ctx_key = m2.group(1)
            val = m2.group(2)
            return context.get(ctx_key) == val
            
        return False

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



