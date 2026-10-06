"""Command-Line Interface for Telegram Archive Cleaner."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn

from tg_cleaner.analyzer.dedupe import DeduplicationEngine
from tg_cleaner.analyzer.links import LinkHealthChecker
from tg_cleaner.analyzer.policy import PolicyAuditor
from tg_cleaner.analyzer.stale import StaleContentAnalyzer
from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.cleaner.executor import DeletionExecutor
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.settings import settings
from tg_cleaner.ingest.desktop_export import parse_desktop_export_json
from tg_cleaner.web.app import create_app

app = typer.Typer(
    name="tg-cleaner",
    help="Intelligent Telegram Archive Cleaner with multi-engine deduplication and safety-first deletion.",
    add_completion=False,
)


@app.command()
def web(
    host: str = typer.Option(settings.web_host, help="Host to bind the web server to"),
    port: int = typer.Option(settings.web_port, help="Port to bind the web server to"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
) -> None:
    """Launch the embedded FastAPI web dashboard."""
    db = DatabaseManager(settings.db_path)
    db.init_db()

    fastapi_app = create_app(db=db)
    typer.echo(f"🚀 Starting Telegram Archive Cleaner dashboard at http://{host}:{port}")
    uvicorn.run(fastapi_app, host=host, port=port, reload=reload)


@app.command()
def login(
    phone: str | None = typer.Option(None, help="Phone number with country code, e.g. +1234567890"),
    session_name: str | None = typer.Option(None, help="Custom session name"),
) -> None:
    """Log in to Telegram MTProto and save authorization session."""
    from tg_cleaner.core.auth import TelegramAuthManager

    auth = TelegramAuthManager(session_name=session_name)
    asyncio.run(auth.login_cli_interactive(phone=phone))


@app.command()
def sync(
    limit: int = typer.Option(100, help="Maximum number of dialogs to fetch"),
    session_name: str | None = typer.Option(None, help="Custom session name"),
    db_path: str = typer.Option(settings.db_path, help="Path to SQLite staging database"),
) -> None:
    """Sync available Telegram dialogs (Saved Messages, channels, groups) into local DB."""
    from tg_cleaner.core.auth import TelegramAuthManager
    from tg_cleaner.ingest.live import LiveIngestor

    auth = TelegramAuthManager(session_name=session_name)
    client = auth.get_client()
    db = DatabaseManager(db_path)
    db.init_db()

    async def _run():
        if not await auth.is_authorized():
            typer.secho("Not authorized. Run `tg-cleaner login` first.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        ingestor = LiveIngestor(client, db)
        dialogs = await ingestor.list_dialogs(limit=limit)
        for d in dialogs:
            db.upsert_chat(d)
        typer.secho(f"✅ Synced {len(dialogs)} dialogs into local database!", fg=typer.colors.GREEN)

    asyncio.run(_run())


@app.command(name="import")
def import_export(
    export_path: Path = typer.Argument(..., help="Path to Telegram Desktop result.json file"),
    db_path: str = typer.Option(settings.db_path, help="Path to SQLite staging database"),
) -> None:
    """Import a Telegram Desktop JSON export archive."""
    if not export_path.is_file():
        typer.secho(f"Error: File not found: {export_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    db = DatabaseManager(db_path)
    db.init_db()

    typer.echo(f"📦 Importing Telegram export from {export_path}...")
    result = parse_desktop_export_json(export_path, db)
    typer.secho(
        f"✅ Imported {result['messages_imported']} messages into chat '{result['chat_title']}' (ID: {result['chat_id']})",
        fg=typer.colors.GREEN,
    )


@app.command()
def scan(
    chat_id: int = typer.Argument(..., help="Target chat ID to audit"),
    db_path: str = typer.Option(settings.db_path, help="Path to SQLite staging database"),
) -> None:
    """Audit chat for duplicates, dead links, and policy-restricted content."""
    db = DatabaseManager(db_path)
    db.init_db()

    chat = db.get_chat(chat_id)
    if not chat:
        typer.secho(
            f"Error: Chat ID {chat_id} not found in database. Import or sync first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"🔍 Running audit pipeline on chat '{chat.title}' (ID: {chat_id})...")
    db.clear_flags_for_chat(chat_id)

    # 1. Deduplication
    dedupe_engine = DeduplicationEngine(db)
    dedupe_engine.detect_duplicates_in_chat(chat_id)

    # 2. Policy auditor
    policy_auditor = PolicyAuditor(db)
    policy_auditor.audit_chat_policy(chat_id)

    # 3. Link health checker
    link_checker = LinkHealthChecker(db)
    asyncio.run(link_checker.check_links_in_chat(chat_id))

    # 4. Stale analyzer
    stale_analyzer = StaleContentAnalyzer(db)
    stale_analyzer.audit_stale_content(chat_id)

    stats = db.get_scan_stats(chat_id)

    typer.secho("✅ Audit completed successfully!", fg=typer.colors.GREEN)
    typer.echo(f"  • Total messages:            {stats.total_messages}")
    typer.echo(f"  • Exact duplicates:          {stats.exact_duplicates}")
    typer.echo(f"  • Same media / diff caption: {stats.same_media_diff_caption}")
    typer.echo(f"  • Dead links / invites:      {stats.dead_links}")
    typer.echo(f"  • Policy restricted:         {stats.policy_restricted}")
    typer.echo(f"  • Deletion candidates:       {stats.total_deletion_candidates}")
    typer.echo(f"  • Reclaimable space:         {stats.estimated_reclaimable_bytes / 1024:.1f} KB")


@app.command()
def delete(
    chat_id: int = typer.Argument(..., help="Target chat ID to delete flagged candidates from"),
    dry_run: bool = typer.Option(
        True, "--dry-run/--live", help="Simulate deletion or perform live deletion"
    ),
    preset: str = typer.Option("KEEP_NEWEST", help="Retention preset for duplicate groups"),
    db_path: str = typer.Option(settings.db_path, help="Path to SQLite staging database"),
) -> None:
    """Execute pre-deletion backup and paced message deletion."""
    db = DatabaseManager(db_path)
    db.init_db()

    candidates = db.get_deletion_candidates(chat_id)
    if not candidates:
        typer.echo(f"No deletion candidates found for chat {chat_id}.")
        return

    candidate_ids = [m.id for m in candidates]
    mode_str = "DRY-RUN SIMULATION" if dry_run else "LIVE TELEGRAM DELETION"
    typer.echo(f"🚀 Preparing {mode_str} for {len(candidate_ids)} messages in chat {chat_id}...")

    executor = DeletionExecutor(
        db=db, min_delay=0.01 if dry_run else 1.2, max_delay=0.02 if dry_run else 2.5
    )

    def on_progress(done: int, total: int):
        typer.echo(f"  Progress: {done}/{total} messages processed...", nl=False)
        typer.echo("\r", nl=False)

    result = asyncio.run(
        executor.delete_candidates(
            chat_id=chat_id,
            message_ids=candidate_ids,
            dry_run=dry_run,
            progress_callback=on_progress,
        )
    )

    typer.echo("")
    typer.secho(
        f"✅ {mode_str} completed! Processed: {result.deleted_count}/{result.total_candidates} messages.",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"   Backup snapshot verified at: {result.backup_file}")


@app.command()
def backups(
    chat_id: int | None = typer.Option(None, help="Filter backups by chat ID"),
) -> None:
    """List verified pre-deletion backups."""
    manager = BackupManager()
    items = manager.list_backups(chat_id=chat_id)
    if not items:
        typer.echo("No pre-deletion backups recorded.")
        return

    typer.echo(f"Found {len(items)} backup snapshots:")
    for b in items:
        typer.echo(
            f"  • {b['filename']} | Chat: {b['chat_id']} | Msgs: {b['message_count']} | Size: {b['size_bytes']}B | SHA256: {b['sha256'][:16]}..."
        )


@app.command()
def version() -> None:
    """Display tg-cleaner version."""
    typer.echo("tg-cleaner version 1.0.0")


def main() -> None:
    """Entry point for CLI execution."""
    app()


if __name__ == "__main__":
    main()
