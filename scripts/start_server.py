import argparse
import os
import sys
from dotenv import load_dotenv


def _parse_runtime_args():
    argv = list(sys.argv[1:])
    normalized = []
    for token in argv:
        if token.startswith("--") and "=" not in token and token != "--help":
            name = token[2:]
            if name and name != "scenario":
                normalized.extend(["--scenario", name])
            else:
                normalized.append(token)
        else:
            normalized.append(token)

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("scenario_positional", nargs="?", default=None)
    parser.add_argument("--scenario", dest="scenario", default=os.environ.get("PATIENT_SCENARIO", "heavy_accent"))
    args = parser.parse_args(normalized)
    return args.scenario or args.scenario_positional or os.environ.get("PATIENT_SCENARIO", "heavy_accent")


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    load_dotenv()
    scenario = _parse_runtime_args()
    os.environ["PATIENT_SCENARIO"] = scenario

    from app.services.ws_server import run_server

    enable_ngrok = os.getenv("ENABLE_NGROK", "false").lower() in ("1", "true", "yes")
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    print(f"Starting FastAPI server on {host}:{port} (ngrok enabled={enable_ngrok}, scenario={scenario})")
    run_server(host=host, port=port, enable_ngrok=enable_ngrok, scenario=scenario)


if __name__ == "__main__":
    main()
