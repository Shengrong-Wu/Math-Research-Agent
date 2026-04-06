from math_agent.lean.compiler import LeanCompiler

class TestCompiler:
    def test_parse_errors(self):
        stderr = "Foo.lean:10:5: error: unknown identifier 'bar'\nFoo.lean:15:2: warning: unused variable"
        errors = LeanCompiler.parse_errors(stderr)
        assert len(errors) >= 1
        assert errors[0].line == 10
        assert errors[0].severity == "error"

    def test_count_sorries(self, tmp_path):
        lean_file = tmp_path / "Test.lean"
        lean_file.write_text("theorem foo : True := by sorry\ntheorem bar : False := by sorry")
        compiler = LeanCompiler(tmp_path)
        count = compiler.count_sorries(lean_file)
        assert count == 2
