"""This is the CodeQL CLI Module."""
import os
import csv
import json
import logging
import tempfile
import subprocess
from glob import glob
from typing import List, Optional, Union

from ghastoolkit.codeql.databases import CodeQLDatabase
from ghastoolkit.codeql.results import CodeQLResults


logger = logging.getLogger("ghastoolkit.codeql.cli")


def findCodeQLBinary() -> Optional[List[str]]:
    """Find CodeQL Binary on current system."""
    actions_location = glob(
        os.path.join(
            os.environ.get("RUNNER_TOOL_CACHE", ""),
            "CodeQL",
            "*",
            "x64",
            "codeql",
            "codeql",
        )
    )
    logger.debug(f"CodeQL Action Location :: {actions_location}")
    locations = [
        # generic
        ["codeql"],
        # local bin
        ["/usr/bin/codeql/codeql"],
        # gh cli
        ["gh", "codeql"],
    ]
    # actions
    if actions_location:
        locations.append([actions_location[0]])

    for location in locations:
        try:
            cmd = location + ["version"]
            with open(os.devnull, "w") as null:
                subprocess.check_call(cmd, stdout=null, stderr=null)
            logger.debug(f"Found CodeQL :: {location}")
            return location
        except Exception as err:
            logger.debug(f"Failed to find codeql :: {err}")
    return []


class CodeQL:
    """CodeQL CLI."""

    def __init__(self, binary: Optional[str] = None) -> None:
        """Initialise CodeQL CLI Class."""
        if binary:
            self.path_binary = [binary]
        else:
            self.path_binary: Optional[list[str]] = findCodeQLBinary()

    def exists(self) -> bool:
        """Check codeql is present on the system."""
        return self.path_binary != None

    def runCommand(self, *argvs, display: bool = False) -> Optional[str]:
        """Run CodeQL command without the binary / path."""
        logger.debug(f"Running CodeQL Command :: {argvs[0]}...")
        if not self.path_binary:
            raise Exception("CodeQL binary / path was not found")
        cmd = []
        cmd.extend(self.path_binary)
        cmd.extend(argvs)

        logger.debug(f"Running Command :: {cmd}")

        if display:
            subprocess.check_output(cmd)
        else:
            result = subprocess.run(cmd, capture_output=True)
            return result.stdout.decode().strip()

    @property
    def version(self) -> str:
        """Get CodeQL Version from the CLI binary."""
        version = self.runCommand("version", "--format", "terse")
        if not version:
            raise Exception("CodeQL version not found")
        return version

    def runQuery(
        self,
        database: CodeQLDatabase,
        path: Optional[str] = None,
        display: bool = False,
    ) -> CodeQLResults:
        """Run a CodeQL Query on a CodeQL Database."""
        if not database.path:
            raise Exception("CodeQL Database path is not set")

        path = path or database.default_pack
        logger.debug(f"Query path :: {path}")

        self.runCommand(
            "database",
            "run-queries",
            "-j",
            "0",
            database.path,
            path,
            display=display,
        )
        if path.endswith(".ql"):
            return self.getResults(database, path)
        return self.getResults(database)

    def runQueryWithParameters(self, database: CodeQLDatabase, path: str, **kwargs):
        """Run a CodeQL query with parameters."""
        return

    def runRawQuery(
        self,
        path: str,
        database: CodeQLDatabase,
        display: bool = False,
        outputtype: str = "sarif",
    ) -> Union[list, CodeQLResults]:
        """Run raw query on a CodeQL Database."""
        if not database.path:
            raise Exception("CodeQL Database path is not set")
        if not path.endswith(".ql"):
            raise Exception("runRawQuery requires a QL file")

        self.runCommand("database", "run-queries", database.path, path, display=display)

        from ghastoolkit.codeql.packs.pack import CodeQLPack

        if ":" in path:
            logger.debug("Running in pack mode")
            pack_name, query_path = path.split(":", 1)
        else:
            logger.debug("Running in path mode")

            pack = CodeQLPack.findByQuery(path)
            pack_name = pack.name
            query_path = path.replace(pack.path + "/", "")

        logger.debug(f"Pack Name for query :: {pack_name} -> {query_path}")

        bqrs_query_path = query_path.replace(".ql", ".bqrs")
        bqrs = os.path.join(database.path, "results", pack_name, bqrs_query_path)

        logger.debug(f"BQRS File location :: {bqrs}")

        if outputtype == "bqrs":
            if not os.path.exists(bqrs):
                raise Exception(f"BQRS file does not exist")
            return self.readBqrs(bqrs, display=display)
        elif outputtype == "sarif":
            return self.getResults(database, path)
        return []

    def getResults(
        self, database: CodeQLDatabase, path: Optional[str] = None
    ) -> CodeQLResults:
        """Get the interpreted results from CodeQL."""
        sarif = os.path.join(tempfile.gettempdir(), "codeql-result.sarif")
        cmd = [
            "database",
            "interpret-results",
            "--format",
            "sarif-latest",
            "--output",
            sarif,
            database.path,
        ]
        if path:
            cmd.append(path)

        self.runCommand(*cmd)

        with open(sarif, "r") as handle:
            data = json.load(handle)

        # clean up
        os.remove(sarif)

        results = data.get("runs", [])[0].get("results", [])
        return CodeQLResults.loadSarifResults(results)

    def readBqrs(
        self,
        bqrsfile: str,
        display: bool = False,
    ) -> list[list[str]]:
        """Read a BQRS file to get the raw results."""
        output = os.path.join(tempfile.gettempdir(), "codeql-result.csv")
        logger.debug(f"Reading BQRS file :: {bqrsfile}")

        self.runCommand(
            "bqrs",
            "decode",
            "--no-titles",
            "--format",
            "csv",
            "--output",
            output,
            bqrsfile,
            display=display,
        )
        results = []
        with open(output, "r") as handle:
            data = csv.reader(handle, delimiter=",")
            for row in data:
                results.append(row)

        # clean up
        os.remove(output)
        return results

    def __str__(self) -> str:
        """To String."""
        if self.path_binary:
            return f"CodeQL('{self.version}')"
        return "CodeQL()"
