#!/usr/bin/python
"""Fail closed if a preflight regression reaches the mutation sentinel."""

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={
            "name": {"type": "list", "elements": "str"},
            "state": {"type": "str"},
        },
        supports_check_mode=True,
    )
    module.fail_json(msg="TICKET10_POST_PREFLIGHT_MUTATION_SENTINEL_REACHED")


if __name__ == "__main__":
    main()
