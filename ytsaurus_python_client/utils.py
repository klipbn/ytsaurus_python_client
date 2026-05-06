def extract_variables(query: str) -> str:
    return "\n".join(
        line for line in query.strip().splitlines() if line.strip().startswith("$")
    )


def strip_variables(query: str) -> str:
    return "\n".join(
        line for line in query.strip().splitlines() if not line.strip().startswith("$")
    )
