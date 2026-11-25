"""Start and load a private Windows PostgreSQL cluster for the synthetic platform benchmark."""
import argparse
from contextlib import closing
from hashlib import file_digest
import io
from pathlib import Path
from secrets import token_hex
import subprocess
import tarfile
from urllib.request import urlopen
from zipfile import ZipFile

from evaluation.platform_adoption import verify_inputs
from evaluation.platform_fixtures import ROOT

RUNTIME = Path(".deps/platform-adoption").resolve()
BIN = RUNTIME / "postgres/bin"
CLUSTER = RUNTIME / "fixture-postgres"
OWNER_PASSWORD = RUNTIME / "fixture-owner.pw"
READER_PASSWORD = RUNTIME / "fixture-reader.pw"
PORT = 55431
ARTIFACT = "embedded-postgres-binaries-windows-amd64-16.11.0.jar"
URL = ("https://repo.maven.apache.org/maven2/io/zonky/test/postgres/"
       "embedded-postgres-binaries-windows-amd64/16.11.0/" + ARTIFACT)
SHA256 = "8563af4423177595d5f9463d986cd4aaf0c161af7d4277154f45e7ce4fecd355"


def run(name, *args):
    subprocess.run([str(BIN / (name + ".exe")), *map(str, args)], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def binaries():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    archive = RUNTIME / ARTIFACT
    if not archive.exists():
        with urlopen(URL, timeout=85) as response, archive.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    with archive.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != SHA256:
            raise ValueError("PostgreSQL binary archive does not match the published SHA-256.")
    with ZipFile(archive) as package:
        entry, = [name for name in package.namelist() if name.endswith((".txz", ".tar.xz"))]
        with tarfile.open(fileobj=io.BytesIO(package.read(entry))) as payload:
            payload.extractall(RUNTIME / "postgres", filter="data")


def start():
    if CLUSTER.exists():
        raise FileExistsError(CLUSTER)
    binaries()
    for path in (OWNER_PASSWORD, READER_PASSWORD):
        path.write_text(token_hex(24), encoding="ascii")
    run("initdb", "-D", CLUSTER, "-U", "fixture_owner", "--auth=scram-sha-256",
        "-E", "UTF8", "--no-locale", "--pwfile", OWNER_PASSWORD)
    run("pg_ctl", "-D", CLUSTER, "-l", RUNTIME / "fixture-postgres.log",
        "-o", f"-p {PORT} -h 127.0.0.1", "-w", "start")


def load(root):
    import psycopg2
    from psycopg2 import sql

    databases = verify_inputs(root)
    admin = OWNER_PASSWORD.read_text("ascii")
    reader = READER_PASSWORD.read_text("ascii")

    def connect(database):
        return psycopg2.connect(host="127.0.0.1", port=PORT, dbname=database,
                                user="fixture_owner", password=admin)

    with closing(connect("postgres")) as owner:
        owner.autocommit = True
        with owner.cursor() as cursor:
            cursor.execute("CREATE ROLE fixture_reader LOGIN PASSWORD %s", (reader,))
            cursor.execute("ALTER ROLE fixture_reader SET default_transaction_read_only=ON")
            for name in databases:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

    for name in databases:
        with closing(connect(name)) as database:
            with database, database.cursor() as cursor:
                cursor.execute((root / (name + ".sql")).read_text(encoding="utf-8"))
                cursor.execute("GRANT USAGE ON SCHEMA public TO fixture_reader")
                cursor.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO fixture_reader")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.action == "start":
        verify_inputs(args.root)
        start()
        try:
            load(args.root)
        except Exception:
            run("pg_ctl", "-D", CLUSTER, "-w", "stop", "-m", "fast")
            raise
    else:
        run("pg_ctl", "-D", CLUSTER, "-w", "stop", "-m", "fast")
