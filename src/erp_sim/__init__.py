"""Composable ERP protocol client. Imports have no network side effects."""
__version__ = '0.11.0'


def main():
    from .cli import main as cli_main
    return cli_main()
