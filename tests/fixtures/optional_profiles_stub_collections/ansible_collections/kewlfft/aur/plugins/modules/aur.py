#!/usr/bin/python
"""No-op AUR fixture used only by the ticket #10 profile tests."""

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={
            "name": {"type": "list", "elements": "str", "default": []},
            "state": {"type": "str"},
            "use": {"type": "str"},
            "upgrade": {"type": "bool", "default": False},
            "aur_only": {"type": "bool", "default": False},
        },
        supports_check_mode=True,
    )
    module.exit_json(changed=False, ticket10_aur_stub=module.params["name"])


if __name__ == "__main__":
    main()
