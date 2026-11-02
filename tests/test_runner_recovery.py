"""Execute the provisioning shell against fakes, never against the host OS."""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from register_runner import remote_script

BASH = os.environ.get("KAIROS_TEST_BASH") or (shutil.which("bash") if os.name != "nt" else None)

@unittest.skipUnless(BASH, "Requires bash; exercised in Linux CI")
class RunnerRecoveryTests(unittest.TestCase):
    def script(self):
        # Execute only prerequisites. No filesystem installation, network,
        # credentials, user creation or systemd commands can run in this test.
        script = remote_script(
            "https://github.com/actions/runner/releases/download/v1/runner.tar.gz",
            "a" * 64, "/kairos/runner/i-123/registration", "us-east-1", "kairos-i-123")
        return script.split("install -d -o kairos-runner", 1)[0]

    def run_shell(self, functions, body):
        return subprocess.run([BASH, "-c", functions + "\n" + body],
                              text=True, capture_output=True)

    def test_failed_cloud_init_recovers_and_existing_user_is_preserved(self):
        functions = '''
cloud-init() { return 1; }
dnf() {
    for package in python3-pip unzip libicu; do
        [[ " $* " == *" $package "* ]] || return 9
    done
    [[ " $* " != *" awscli2 "* ]] || return 10
}
aws() { echo aws-cli/2-test; }
created=0
id() { (( created > 0 )); }
useradd() { created=$((created+1)); }
'''
        result = self.run_shell(functions, self.script() + self.script() + '\n[[ "$created" == 1 ]]')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("repairing runner prerequisites", result.stderr)
        self.assertIn("aws-cli/2-test", result.stdout)

    def test_dependency_failure_stops_before_user_registration(self):
        functions = '''
cloud-init() { return 1; }
dnf() { return 23; }
useradd() { echo SHOULD_NOT_RUN; }
'''
        result = self.run_shell(functions, self.script())
        self.assertEqual(result.returncode, 23)
        self.assertNotIn("SHOULD_NOT_RUN", result.stdout)

    def test_missing_cli_uses_al2023_package(self):
        functions = '''
cloud-init() { return 0; }
command() { return 1; }
dnf() { echo "$*"; }
aws() { return 0; }
id() { return 0; }
useradd() { echo SHOULD_NOT_RUN; }
'''
        result = self.run_shell(functions, self.script())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("install -y awscli-2", result.stdout)
        self.assertNotIn("SHOULD_NOT_RUN", result.stdout)
