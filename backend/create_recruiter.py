"""Create the first recruiter securely from a terminal prompt."""

import argparse
import asyncio
import getpass

from auth import create_recruiter_account


async def create_recruiter(email: str, name: str, password: str) -> None:
    try:
        recruiter = await create_recruiter_account(email, name, password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Recruiter account created for {recruiter['email']}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an iSOFT recruiter account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    asyncio.run(create_recruiter(args.email, args.name, password))


if __name__ == "__main__":
    main()
