"""Simple hello module with greeting and arithmetic utilities."""


def greet(name: str) -> None:
    """Print a greeting message to the given name.

    Args:
        name: The name to greet.
    """
    print(f"Hello, {name}!")


def add(a: int, b: int) -> int:
    """Return the sum of two integers.

    Args:
        a: The first integer.
        b: The second integer.

    Returns:
        The sum of a and b.
    """
    return a + b


def main() -> None:
    """Run the main entry point of the module."""
    greet("World")
    result: int = add(5, 3)
    print(f"5 + 3 = {result}")


if __name__ == "__main__":
    main()
