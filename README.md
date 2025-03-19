# MCP Tools

A custom Model Context Protocol (MCP) server implementation that provides file system and command execution tools for Claude Desktop and other LLM clients.

## What is the Model Context Protocol?

The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context to Large Language Models (LLMs). Much like a USB-C port provides a standardized way to connect devices to various peripherals, MCP provides a standardized way to connect AI models to different data sources and tools.

This project implements a FastMCP server with several useful tools that enable Claude and other LLMs to interact with your local file system and execute commands. It extends LLMs' capabilities with local system access in a controlled way through well-defined tool interfaces.

## Key Benefits of MCP

- **Standardized Integration**: MCP provides a growing list of pre-built integrations that your LLM can directly plug into
- **Vendor Flexibility**: Easily switch between LLM providers and vendors (Claude, GPT-4o, Gemini, etc.)
- **Security**: Best practices for securing your data within your infrastructure
- **Tool Exposure**: Encapsulate existing tools and make them accessible to any MCP-compatible LLM client

## Features

The MCP server provides the following file system and command execution tools:

- **execute_shell_command**: Execute shell commands and get stdout/stderr results
- **show_file**: View file contents with optional line range specification
- **search_in_file**: Search for patterns in files using regular expressions
- **edit_file**: Make precise changes to files with string replacements and line operations
- **write_file**: Write or append content to files

## MCP Architecture

MCP follows a client-server architecture:

- **Hosts**: LLM applications (like Claude Desktop or IDEs) that initiate connections
- **Clients**: Maintain 1:1 connections with servers, inside the host application
- **Servers**: Provide context, tools, and prompts to clients (this project implements a server)

## Prerequisites

- Python 3.10 or higher
- An MCP-compatible client (Claude Desktop, or any other client that supports MCP)

## Installation

1. [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
2. Clone this repository or download the source code
3. Run `uv run mcp install` to install the MCP server
4. Run `which uv` to get an absolute path to the `uv` executable
5. Update your MCP server configuration in Claude Desktop to use the absolute path to the `uv` executable


## Usage

### Connecting from Claude Desktop

1. Open Claude Desktop
2. Connect to the MCP server using the identifier "zbigniew-mcp"

> **Note**: While this implementation focuses on Claude Desktop, MCP is designed to be compatible with any MCP-compatible tool or LLM client, providing flexibility in implementation and integration.

## Available Tools

### execute_shell_command

Execute shell commands safely using a list of arguments:

```python
execute_shell_command(["ls", "-la"])
execute_shell_command(["grep", "-r", "TODO", "./src"])
execute_shell_command(["python", "analysis.py", "--input", "data.csv"])
execute_shell_command(["uname", "-a"])
```

### show_file

View file contents with optional line range specification:

```python
show_file("/path/to/file.txt")
show_file("/path/to/file.txt", num_lines=10)
show_file("/path/to/file.txt", start_line=5, num_lines=10)
```

### search_in_file

Search for patterns in files using regular expressions:

```python
search_in_file("/path/to/script.py", r"def\s+\w+\s*\(")
search_in_file("/path/to/code.py", r"#\s*TODO", case_sensitive=False)
```

### edit_file

Make precise changes to files:

```python
# Replace text
edit_file("config.json", replacements={"\"debug\": false": "\"debug\": true"})

# Insert at line 5
edit_file("script.py", line_operations=[{"operation": "insert", "line": 5, "content": "# New comment"}])

# Delete lines 10-15
edit_file("file.txt", line_operations=[{"operation": "delete", "start_line": 10, "end_line": 15}])

# Replace line 20
edit_file("file.txt", line_operations=[{"operation": "replace", "line": 20, "content": "Updated content"}])
```

### write_file

Write or append content to files:

```python
# Overwrite file
write_file("/path/to/file.txt", "New content")

# Append to file
write_file("/path/to/log.txt", "Log entry", mode="a")
```

## Transport Mechanisms

MCP supports multiple transport methods for communication between clients and servers:

- **Standard Input/Output (stdio)**: Uses standard input/output for communication, ideal for local processes
- **Server-Sent Events (SSE)**: Enables server-to-client streaming with HTTP POST requests for client-to-server communication

This implementation uses a local MCP server that communicates via text input/output.

## Extending with Your Own Tools

You can easily extend this MCP server by adding new tools with the `@mcp.tool` decorator. Follow the pattern in server.py to create new tools that expose additional functionality to your LLM clients.

## Related Projects

- [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters): Use MCP with LangChain
- [MCP-Bridge](https://github.com/SecretiveShell/MCP-Bridge): Map MCP tools to OpenAI's format

## Security Considerations

The MCP server provides Claude with access to your local system. Be mindful of the following:

- The server executes shell commands as your user
- It can read, write, and modify files on your system
- Consider limiting access to specific directories if security is a concern
