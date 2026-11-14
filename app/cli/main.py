from __future__ import annotations

import click

from app.cli.commands import (
    apply_group,
    diagnose_group,
    explain_group,
    get_group,
    preview_group,
    render_group,
    sync_group,
)


@click.group(name="subhub")
def cli() -> None:
    """SubHub command line client."""


cli.add_command(get_group)
cli.add_command(preview_group)
cli.add_command(apply_group)
cli.add_command(render_group)
cli.add_command(explain_group)
cli.add_command(diagnose_group)
cli.add_command(sync_group)


if __name__ == "__main__":
    cli()
