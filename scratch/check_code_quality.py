import ast
import os
import builtins

class ScopeVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.scopes = [set(dir(builtins))]
        self.undefined = []

    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname or alias.name.split('.')[0]
            self.scopes[-1].add(name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            name = alias.asname or alias.name
            self.scopes[-1].add(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.scopes[-1].add(node.name)
        fn_scope = set()
        for arg in node.args.args + node.args.kwonlyargs:
            fn_scope.add(arg.arg)
        if node.args.vararg:
            fn_scope.add(node.args.vararg.arg)
        if node.args.kwarg:
            fn_scope.add(node.args.kwarg.arg)

        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Param)):
                fn_scope.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        fn_scope.add(alias.asname or alias.name.split('.')[0])
                else:
                    for alias in child.names:
                        fn_scope.add(alias.asname or alias.name)

        self.scopes.append(fn_scope)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_ClassDef(self, node):
        self.scopes[-1].add(node.name)
        class_scope = set()
        self.scopes.append(class_scope)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            name = node.id
            found = False
            for scope in reversed(self.scopes):
                if name in scope:
                    found = True
                    break
            if not found and name not in ['__file__', '__name__', '__doc__', '__module__']:
                self.undefined.append((node.lineno, name))
        self.generic_visit(node)

def analyze_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=path)
    except Exception as e:
        print(f"[SYNTAX ERROR] {path}: {e}")
        return

    visitor = ScopeVisitor(path)
    visitor.visit(tree)
    if visitor.undefined:
        seen = set()
        for lineno, name in visitor.undefined:
            if name not in seen:
                seen.add(name)
                print(f"[POTENTIAL UNDEFINED] {path}:{lineno} -> {name}")

def main():
    dirs = ['common', 'Trade_Option', 'Trade_Stock']
    for d in dirs:
        for root, _, files in os.walk(d):
            for file in files:
                if file.endswith('.py'):
                    analyze_file(os.path.join(root, file))

if __name__ == '__main__':
    main()
