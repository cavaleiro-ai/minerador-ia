"""Inicia o Minerador IA: servidor web local + navegador."""
import argparse
import os
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(description="Minerador IA")
    parser.add_argument("--host", default=os.environ.get("MINERADOR_HOST", "127.0.0.1"))
    parser.add_argument("--porta", type=int, default=int(os.environ.get("MINERADOR_PORTA", "8765")))
    parser.add_argument(
        "--sem-navegador",
        action="store_true",
        default=os.environ.get("MINERADOR_SEM_NAVEGADOR", "") == "1",
    )
    args = parser.parse_args()

    import uvicorn
    from minerador.server import app

    url = f"http://127.0.0.1:{args.porta}"
    print(f"Minerador IA rodando em {url}  (feche esta janela para encerrar)")
    if not args.sem_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.porta, log_level="warning")


if __name__ == "__main__":
    main()
