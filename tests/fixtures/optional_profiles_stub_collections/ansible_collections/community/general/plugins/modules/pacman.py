#!/usr/bin/python
"""No-op Pacman fixture used only by the ticket #10 profile tests."""

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={
            "name": {"type": "list", "elements": "str"},
            "state": {"type": "str"},
            "update_cache": {"type": "bool", "default": False},
            "upgrade": {"type": "bool", "default": False},
        },
        supports_check_mode=True,
    )
    module.exit_json(changed=False, ticket10_package_stub=module.params["name"])


if __name__ == "__main__":
    main()
