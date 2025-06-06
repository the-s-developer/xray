from mcp.server.fastmcp import FastMCP
from pw_runner.runner import execute_python_code
from dotenv import load_dotenv
load_dotenv()



mcp = FastMCP("pw_simulator")
@mcp.tool(
    name="execute_python_scraper_code",
    description=(
        "Executes a Python code string in the python environment. "
        "The environment has Playwright, BeautifulSoup (bs4), and httpx, requests, pre-installed and ready to use. "
        "Define a `RESULT` dictionary in your code, and it will be automatically returned as a JSON result. "
        "Do not need to import or define any extra function; simply assign your result to `RESULT`. "
        "**Important:** Do not use a main function or `if __name__ == '__main__':` block in your script. "
        "Example Code:"
        "```python\n"
        "#MAX_COUNT = ...  (will be injected)\n"
        "RESULT=[] #will be returned as json data"
        "for i, item in enumerate(...):\n"
        "    if i >= MAX_COUNT:\n"
        "        break\n"
        "```\n"
    )

)
async def execute_python_scraper_code(code: str):
    with open("my_mcp.log", "a") as f:
        f.write("---------------------------------------------------------------------------MCP-Code: {}\n".format(code))
    result = await execute_python_code(code, no_prints=False)
    with open("my_mcp.log", "a") as f:
        f.write("-------------------------RESULT: {}\n".format(result))
    return result


if __name__ == "__main__":
    mcp.run()
