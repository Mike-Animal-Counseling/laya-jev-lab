"""Use the installed engine without starting the demo or a database."""
import argparse
import getpass
import json
from ticket_engine import EngineError, TicketEngine, compare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("laya", "jev", "compare"), default="laya")
    parser.add_argument("--model-path", default="models/ticket-finetuned-v5")
    parser.add_argument("--subject", default="订阅重复扣款")
    parser.add_argument("--message", default="本月订阅被扣了两次，请帮我退回多扣的款项。")
    args = parser.parse_args()
    try:
        if args.engine == "laya":
            result = TicketEngine("laya", model_path=args.model_path).classify(args.message, subject=args.subject)
        else:
            # Never pass API credentials in command-line arguments or output.
            key = getpass.getpass("Your Jev API key (hidden): ")
            jev = TicketEngine("jev", api_key=key)
            result = (jev.classify(args.message, subject=args.subject) if args.engine == "jev"
                      else compare(TicketEngine("laya", model_path=args.model_path), jev, args.message, subject=args.subject))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    except EngineError as exc:
        parser.exit(1, f"{exc.code}: {exc}\n")


if __name__ == "__main__":
    main()
