import unittest
import runner

class TestSandboxSecurity(unittest.TestCase):
    def test_safe_code(self):
        code = "print('Safe output!')"
        res = runner.run_isolated_code(code)
        self.assertTrue(res["success"])
        self.assertEqual(res["stdout"].strip(), "Safe output!")

    def test_blocks_os_import(self):
        code = "import os\nos.listdir('.')"
        res = runner.run_isolated_code(code)
        self.assertFalse(res["success"])
        self.assertIn("Security Sandbox", res["stderr"])
        self.assertIn("المكتبة المحظورة 'os'", res["stderr"])

    def test_blocks_subprocess_import(self):
        code = "from subprocess import run\nrun('dir', shell=True)"
        res = runner.run_isolated_code(code)
        self.assertFalse(res["success"])
        self.assertIn("Security Sandbox", res["stderr"])

    def test_blocks_open_call(self):
        code = "f = open('secret.txt', 'w')"
        res = runner.run_isolated_code(code)
        self.assertFalse(res["success"])
        self.assertIn("الدالة المحظورة 'open()'", res["stderr"])

    def test_blocks_eval_exec(self):
        code = "eval('1 + 1')"
        res = runner.run_isolated_code(code)
        self.assertFalse(res["success"])
        self.assertIn("الدالة المحظورة 'eval()'", res["stderr"])

    def test_blocks_dunder_exploit(self):
        code = "x = ().__class__.__bases__[0].__subclasses__()"
        res = runner.run_isolated_code(code)
        self.assertFalse(res["success"])
        self.assertIn("__subclasses__", res["stderr"])

    def test_timeout_protection(self):
        code = "while True: pass"
        res = runner.run_isolated_code(code, timeout=2)
        self.assertFalse(res["success"])
        self.assertIn("انتهى الوقت المحدد", res["stderr"])

if __name__ == "__main__":
    unittest.main()

