from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio
import time

async def main():
    server_params = StdioServerParameters(
        command="npx",
        args=["-y","@playwright/mcp@latest"]
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            while True:
                tools = await session.list_tools()
                print("TOOL LIST:", tools)
                # Sonra bir tool çağrısı
                result = await session.call_tool("browser_navigate", {"url": "https://meb.gov.tr"})
                print("TOOL RESULT:", result)
                time.sleep(2)
                result = await session.call_tool("browser_navigate", {"url": "https://www.meb.gov.tr/meb_duyuruindex.php"})
                print("TOOL RESULT:", result)
                time.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
