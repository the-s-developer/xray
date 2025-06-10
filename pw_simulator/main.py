from mcp.server.fastmcp import FastMCP
from pw_runner.runner import execute_python_code
from dotenv import load_dotenv
load_dotenv()



mcp = FastMCP("python_environment")
@mcp.tool(
    name="execute",
    description=(
        "Executes a Python code string in the python environment. "
        "Uses Python 3.11. "
        "The environment has Playwright, BeautifulSoup (bs4), and httpx, requests, pre-installed and ready to use. "
        "Define a `OUTPUT` dictionary in your code, and it will be automatically returned as a result. "
        "**Important:** Do not use a main function or `if __name__ == '__main__':` block in your script. "
    )

)
async def execute(python_code: str):
    return  await execute_python_code(python_code, no_prints=False)


if __name__ == "__main__":
    mcp.run()
