from .config import add_arguments  # noqa: F401  (re-exported as the contract)

NAME = "schedule"
HELP = "Run Claude Code unattended, looping in the foreground"


def run(args):
    # Real implementation arrives in Task 7. Returning 0 keeps `lmi schedule`
    # importable and the contract test green; nothing calls it until then.
    return 0
