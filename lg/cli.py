import typer

app = typer.Typer()


@app.command()
def discover(
    refresh: bool = typer.Option(False, "--refresh"),
    limit_zones: int | None = typer.Option(None, "--limit-zones"),
    category: list[str] | None = typer.Option(None, "--category"),
):
    import lg.db
    import lg.discover

    lg.db.init_db()
    lg.discover.run(refresh=refresh, limit_zones=limit_zones, categories=category)


@app.command()
def classify(refresh: bool = typer.Option(False, "--refresh")):
    import lg.db
    import lg.classify

    lg.db.init_db()
    lg.classify.run(refresh=refresh)


@app.command()
def audit(refresh: bool = typer.Option(False, "--refresh")):
    import lg.db
    import lg.audit

    lg.db.init_db()
    lg.audit.run(refresh=refresh)


@app.command()
def score():
    import lg.db
    import lg.score

    lg.db.init_db()
    lg.score.run()


@app.command()
def run():
    import lg.db
    import lg.discover
    import lg.classify
    import lg.audit
    import lg.score
    from sqlmodel import func, select

    lg.db.init_db()
    lg.discover.run(refresh=False)
    lg.classify.run(refresh=False)
    lg.audit.run(refresh=False)
    lg.score.run()

    with lg.db.session() as s:
        places = s.exec(select(func.count()).select_from(lg.db.Place)).one()
        checks = s.exec(select(func.count()).select_from(lg.db.SiteCheck)).one()
        leads = s.exec(select(func.count()).select_from(lg.db.Lead)).one()
    print(f"places={places} site_checks={checks} leads={leads}")


if __name__ == "__main__":
    app()
