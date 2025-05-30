from mcp.server.fastmcp import FastMCP
from pw_runner.runner import execute_python_code
from dotenv import load_dotenv
load_dotenv()


mcp = FastMCP("pw_simulator")
@mcp.tool(
    name="execute_python_scraper_code",
    description=(
        "Executes a Python code string in an isolated environment. "
        "The environment has Playwright, BeautifulSoup (bs4), and httpx pre-installed and ready to use. "
        "You can define a `RESULT` dictionary in your code, and it will be automatically returned as a JSON result. "
        "You do not need to import or define any extra function; simply assign your result to `RESULT`. "
        "**Important:** Do not use a main function or `if __name__ == '__main__':` block in your script. "
        "All code must be in the global scope for automatic result injection to work."
    )
)
async def execute_python_scraper_code(code: str):
    return await execute_python_code(code,no_prints=False)

if __name__ == "__main__":
    mcp.run()
