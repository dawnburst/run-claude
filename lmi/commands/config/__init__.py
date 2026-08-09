"""`lmi config` - switch Claude Code between configurations.

The four-name command contract (NAME, HELP, add_arguments, run) is completed in
Task 6; this module is not registered in lmi/commands/__init__.py until run()
exists, so that test_every_command_satisfies_the_contract cannot see a
half-built command.
"""
