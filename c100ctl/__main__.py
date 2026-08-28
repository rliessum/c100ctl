from __future__ import annotations

import sys


def main() -> int:
    from .cli import (
        build_parser,
        cmd_advanced,
        cmd_bind,
        cmd_light,
        cmd_list,
        cmd_profile,
        cmd_provision,
        cmd_status,
    )

    argv = sys.argv[1:]
    if not argv or argv[0] in ("gui", "--gui"):
        from .gui import main as gui_main

        return gui_main()

    parser = build_parser()
    args = parser.parse_args()
    cmd = args.cmd
    if cmd == "daemon":
        from .daemon import main as daemon_main

        return daemon_main()
    if cmd == "doctor":
        from .doctor import run

        return run()
    if cmd == "status":
        return cmd_status(args)
    if cmd == "list":
        return cmd_list(args)
    if cmd == "bind":
        return cmd_bind(args)
    if cmd == "provision":
        return cmd_provision(args)
    if cmd == "light":
        return cmd_light(args)
    if cmd == "profile":
        return cmd_profile(args)
    if cmd == "advanced":
        return cmd_advanced(args)
    if cmd == "gui":
        from .gui import main as gui_main

        return gui_main()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
