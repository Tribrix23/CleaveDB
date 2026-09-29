class CleaveQLError(Exception):
    def __init__(self, message, line=0, column=0, source_line="", suggestion=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.source_line = source_line
        self.suggestion = suggestion

    def format(self, use_color=True) -> str:
        reset = "\033[0m" if use_color else ""
        red = "\033[91m" if use_color else ""
        yellow = "\033[93m" if use_color else ""
        
        output = []
        output.append(f"{red}Error:{reset} {self.message}")
        if self.source_line:
            output.append(f"Line {self.line}: {self.source_line}")
            if self.column > 0:
                output.append(" " * (9 + len(str(self.line)) + self.column - 1) + f"{yellow}^{reset}")
        if self.suggestion:
            output.append(f"{yellow}Did you mean: {self.suggestion}?{reset}")
            
        return "\n".join(output)
