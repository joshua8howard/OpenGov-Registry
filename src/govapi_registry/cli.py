import argparse
import json
from pathlib import Path

from .database import RegistryDatabase


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="govapi",
        description="GovAPI Registry tools. Run without a subcommand to start the API.",
    )
    subcommands = parser.add_subparsers(dest="command")

    import_parser = subcommands.add_parser("import", help="Import API records from JSON")
    import_parser.add_argument("file", type=Path)
    import_parser.add_argument("--source", dest="source_id", help="Source identifier applied to all imported records")
    import_parser.add_argument("--database", default="registry.db")

    reset_parser = subcommands.add_parser("reset", help="Delete and rebuild the registry from seed.json")
    reset_parser.add_argument("--database", default="registry.db")

    discover_parser = subcommands.add_parser("discover", help="Discover records from a catalog connector")
    discover_parser.add_argument(
        "--source",
        choices=["datagov", "socrata", "ckan", "california", "new-york", "texas"],
        default="datagov",
    )
    discover_parser.add_argument("--limit", type=int, default=100)
    discover_parser.add_argument("--ckan-url", default="https://demo.ckan.org")
    discover_parser.add_argument("--database", default="registry.db")

    verify_parser = subcommands.add_parser("verify", help="Verify one registered API")
    verify_parser.add_argument("record_id")
    verify_parser.add_argument("--database", default="registry.db")

    openapi_parser = subcommands.add_parser("openapi", help="Discover an OpenAPI specification")
    openapi_parser.add_argument("record_id")
    openapi_parser.add_argument("--database", default="registry.db")

    execute_parser = subcommands.add_parser("execute", help="Execute a built-in government API connector")
    execute_parser.add_argument("connector", choices=["congress", "fec"])
    execute_parser.add_argument("operation")
    execute_parser.add_argument("--params", default="{}", help="JSON request parameters")
    execute_parser.add_argument("--api-key")

    serve_parser = subcommands.add_parser("serve", help="Run the API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.command is None:
        import uvicorn
        uvicorn.run("govapi_registry.api:app", host="127.0.0.1", port=8000)

    elif args.command == "reset":
        db_path = Path(args.database)
        if db_path.exists():
            db_path.unlink()
        db = RegistryDatabase(db_path)
        db.initialize()
        seed_path = Path(__file__).resolve().parents[2] / "data" / "seed.json"
        with seed_path.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        print(f"Reset and imported {db.import_json(records)} records")

    elif args.command == "import":
        with args.file.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            parser.error("JSON import must contain a list of API records")
        db = RegistryDatabase(args.database)
        db.initialize()
        print(f"Imported {db.import_json(records, source_id=args.source_id)} records")

    elif args.command == "discover":
        from .connectors.datagov import DataGovConnector
        from .connectors.socrata import SocrataConnector
        from .connectors.ckan import CKANConnector
        from .discovery import run_discovery

        db = RegistryDatabase(args.database)
        db.initialize()
        if args.source == "datagov":
            connector = DataGovConnector()
        elif args.source == "socrata":
            connector = SocrataConnector()
        elif args.source == "california":
            connector = CKANConnector("https://data.ca.gov")
        elif args.source == "new-york":
            connector = SocrataConnector("data.ny.gov", jurisdiction="state")
        elif args.source == "texas":
            connector = SocrataConnector("data.texas.gov", jurisdiction="state")
        else:
            connector = CKANConnector(args.ckan_url)
        try:
            result = run_discovery(connector, db, limit=args.limit)
        except Exception as exc:
            parser.error(f"{args.source} discovery failed: {exc}")
        print(json.dumps(result))

    elif args.command == "verify":
        from .verification import EndpointVerifier

        db = RegistryDatabase(args.database)
        db.initialize()
        record = db.get(args.record_id)
        if record is None:
            parser.error(f"API record not found: {args.record_id}")
        result = EndpointVerifier().verify(str(record.base_url))
        db.record_verification(record.id, result)
        print(json.dumps({**result, "last_verified": result["last_verified"].isoformat()}, default=str))

    elif args.command == "openapi":
        from .openapi import OpenAPIDiscovery

        db = RegistryDatabase(args.database)
        db.initialize()
        record = db.get(args.record_id)
        if record is None:
            parser.error(f"API record not found: {args.record_id}")
        result = OpenAPIDiscovery().discover(str(record.documentation_url))
        if result:
            db.set_openapi_spec(record.id, result["openapi_spec_url"])
        print(json.dumps(result))

    elif args.command == "execute":
        from .connectors import CongressGovConnector, FECConnector

        try:
            parameters = json.loads(args.params)
        except json.JSONDecodeError as exc:
            parser.error(f"Invalid --params JSON: {exc}")
        if not isinstance(parameters, dict):
            parser.error("--params must be a JSON object")

        connector = (
            CongressGovConnector(api_key=args.api_key)
            if args.connector == "congress"
            else FECConnector(api_key=args.api_key)
        )
        try:
            response = connector.execute(args.operation, parameters)
        except Exception as exc:
            parser.error(str(exc))
        print(json.dumps({
            "connector_id": connector.connector_id,
            "operation": args.operation,
            "response": response,
            "normalized": connector.normalize_response(response),
        }, default=str))

    elif args.command == "serve":
        import uvicorn
        uvicorn.run("govapi_registry.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
