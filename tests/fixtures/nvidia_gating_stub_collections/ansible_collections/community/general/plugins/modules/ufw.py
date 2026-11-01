#!/usr/bin/python
"""Fail-closed UFW fixture that must never run in NVIDIA-tagged tests."""

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={
            "direction": {"type": "str"},
            "policy": {"type": "str"},
            "state": {"type": "str"},
        },
        supports_check_mode=True,
    )
    module.fail_json(msg="UFW fixture executed outside the NVIDIA tag boundary")


if __name__ == "__main__":
    main()
