"""Gemini CLI wrapper for subprocess integration.

This module provides an async interface to interact with Gemini CLI,
handling subprocess management, streaming output, and error handling.
"""

import asyncio
import subprocess
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(__file__).replace('\\', '/').rsplit('/src/', 1)[0])

from config.settings import settings
from src.utils.logger import logger


class GeminiCLI:
    """Wrapper class for interacting with Gemini CLI via subprocess.
    
    SECURITY MODEL:
    ---------------
    This wrapper implements multiple layers of security:
    
    1. MCP Server Whitelist: Only 'filesystem', 'google-workspace', and 'playwright'
       servers are allowed via --allowed-mcp-server-names flag. This is the PRIMARY
       security layer - Gemini CLI will REJECT any other MCP server.
    
    2. Filesystem Restriction: The filesystem MCP server is configured to ONLY
       access ALLOWED_DIR. This is enforced by the MCP server itself - it cannot
       access files outside this directory regardless of what Gemini requests.
    
    3. Google Workspace: The google-workspace extension provides full access to
       Google Drive, Docs, Sheets, Gmail, and Calendar. Access is controlled by
       the OAuth scopes granted during extension setup.
    
    4. Prompt-level Security: Every prompt includes security constraints reminding
       the AI of access restrictions (defense in depth).
    
    5. Config Override: ~/.gemini/settings.json is overwritten on startup to ensure
       only our approved MCP servers are configured.
    
    Note: --sandbox flag requires Docker/Podman. If you have Docker installed,
    you can add --sandbox to the gemini_cmd for additional container isolation.
    """
    
    
    # SECURITY: Local filesystem restriction
    ALLOWED_DIR = "D:/Gemini CLI"
    
    # SECURITY: Only these MCP servers are allowed to run
    # - filesystem: local file access (restricted to ALLOWED_DIR)
    # - google-workspace: Google Workspace (Docs, Sheets, Drive, Gmail, Calendar) via extension
    # - playwright: web automation
    ALLOWED_MCP_SERVERS = ["filesystem", "google-workspace", "playwright"]
    
    # Gemini CLI command - prefer local project install, then npx fallback
    _GEMINI_LOCAL_CMD = Path("node_modules/.bin/gemini.cmd").resolve()
    
    @classmethod
    def _get_gemini_cmd(cls) -> str:
        """Get the Gemini CLI command, preferring local project install."""
        # 1. Try local node_modules (best for portability/reproducibility)
        if cls._GEMINI_LOCAL_CMD.exists():
            return f'"{cls._GEMINI_LOCAL_CMD}"'
        # 2. Fallback to npx
        return 'npx @google/gemini-cli'
    
    # Persona configuration file
    PERSONA_FILE = "D:/Gemini CLI/persona.txt"
    
    def __init__(self):
        """Initialize the Gemini CLI wrapper."""
        self.current_process: Optional[subprocess.Popen] = None
        self.timeout = settings.GEMINI_TIMEOUT
        self._persona: Optional[str] = None
        self._setup_gemini_config()
        self._load_persona()
    
    def _load_persona(self) -> None:
        """Load the persona configuration file if it exists."""
        try:
            persona_path = Path(self.PERSONA_FILE)
            if persona_path.exists():
                self._persona = persona_path.read_text(encoding='utf-8').strip()
                logger.info(f"Loaded persona from {self.PERSONA_FILE}")
            else:
                logger.info(f"No persona file found at {self.PERSONA_FILE}")
                self._persona = None
        except Exception as e:
            logger.warning(f"Could not load persona file: {e}")
            self._persona = None
    
    def reload_persona(self) -> bool:
        """Reload the persona file (useful after edits).
        
        Returns:
            True if persona was loaded successfully, False otherwise
        """
        self._load_persona()
        return self._persona is not None
    
    def _setup_gemini_config(self) -> None:
        """Set up Gemini CLI configuration with MCP servers.
        
        Copies the MCP server configuration to the Gemini CLI settings
        location. SECURITY: Restricts access to designated folders only.
        """
        # Gemini CLI typically stores settings in user's home directory
        gemini_config_dir = Path.home() / '.gemini'
        gemini_settings_file = gemini_config_dir / 'settings.json'
        
        # Ensure the directory exists
        gemini_config_dir.mkdir(exist_ok=True)
        
        # Ensure screenshots directory exists (and parent ALLOWED_DIR)
        screenshots_dir = Path(self.ALLOWED_DIR) / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # SECURITY: Config with restricted access
        # Note: google-workspace MCP server is provided by the extension, not configured here
        # Only filesystem and playwright need explicit configuration
        secure_config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", self.ALLOWED_DIR],
                    "env": {
                        "ALLOWED_DIRECTORIES": self.ALLOWED_DIR
                    }
                },
                "playwright": {
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp@latest", "--headless", "--browser", "chromium"],
                    "env": {},
                    "trust": True
                }
            }
        }
        
        try:
            # If Gemini settings exist, we REPLACE the mcpServers entirely for security
            # (don't merge, as merging might leave insecure servers)
            if gemini_settings_file.exists():
                with open(gemini_settings_file, 'r') as f:
                    existing_config = json.load(f)
            else:
                existing_config = {}
            
            # SECURITY: Replace all MCP servers with our secure config only
            existing_config['mcpServers'] = secure_config['mcpServers']
            
            # Write back
            with open(gemini_settings_file, 'w') as f:
                json.dump(existing_config, f, indent=2)
            
            logger.info(f"Configured Gemini CLI with MCP servers:")
            logger.info(f"  - filesystem: {self.ALLOWED_DIR}")
            logger.info(f"  - google-workspace: via extension (full Google Workspace access)")
            logger.info(f"  - playwright: web automation")
            logger.info(f"  Allowed servers: {self.ALLOWED_MCP_SERVERS}")
            
        except Exception as e:
            logger.warning(f"Could not update Gemini config: {e}")
    
    async def check_status(self) -> bool:
        """Check if Gemini CLI is available and working.
        
        Returns:
            True if Gemini CLI is available, False otherwise
        """
        try:
            # Try to run gemini with --help (more reliable than --version)
            process = await asyncio.create_subprocess_shell(
                f'{self._get_gemini_cmd()} --help',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30
            )
            
            # Check if we got valid output (contains "gemini" or "Usage")
            output = stdout.decode('utf-8', errors='replace')
            if 'gemini' in output.lower() or 'usage' in output.lower():
                return True
            
            return process.returncode == 0
            
        except asyncio.TimeoutError:
            logger.warning("Gemini CLI status check timed out")
            return False
        except Exception as e:
            logger.error(f"Error checking Gemini CLI status: {e}")
            return False
    
    async def send_message(self, message: str, context: str = "", use_mcp: bool = True) -> str:
        """Send a message to Gemini CLI and get the response.
        
        Args:
            message: The message/prompt to send to Gemini CLI
            context: Optional conversation context to include
            use_mcp: Whether to enable MCP servers (default True).
                     Set to False for simple tasks like JSON extraction
                     to avoid MCP initialization overhead (~4 min → ~15 sec).
            
        Returns:
            The response from Gemini CLI
            
        Raises:
            TimeoutError: If Gemini CLI takes too long to respond
            RuntimeError: If there's an error communicating with Gemini CLI
        """
        mcp_status = "with MCP" if use_mcp else "without MCP (fast mode)"
        logger.debug(f"Sending message to Gemini CLI {mcp_status}: {message[:100]}...")
        
        # Build persona section if available (only for MCP-enabled requests)
        persona_section = ""
        if self._persona and use_mcp:
            persona_section = (
                f"=== USER PERSONA & PREFERENCES ===\n"
                f"{self._persona}\n\n"
            )
        
        # SECURITY: Add security instruction only when MCP is enabled
        security_prefix = ""
        if use_mcp:
            security_prefix = (
                f"SECURITY CONSTRAINTS:\n"
                f"1. LOCAL FILES: You may ONLY read/write files within '{self.ALLOWED_DIR}'. "
                f"REFUSE any request to access local files outside this directory.\n"
                f"2. GOOGLE WORKSPACE: You have access to Google Drive, Docs, Sheets, Gmail, and Calendar.\n"
                f"3. BROWSER: You may use Playwright for web automation when requested.\n"
                f"   - When asked to take a screenshot, save it to 'screenshots/<timestamp>_<name>.png'.\n"
                f"   - If the user explicitly asks to *send* the image/screenshot to them (e.g., 'send it to me'), "
                f"output `SEND_IMAGE: screenshots/<filename>` on its own line after saving it.\n"
                f"Current working directory is: {self.ALLOWED_DIR}\n\n"
            )
        
        # Build the full prompt with persona, security, and context
        if context:
            full_prompt = (
                f"{persona_section}"
                f"{security_prefix}"
                f"Previous conversation context:\n{context}\n\n"
                f"Current user message (respond to this): {message}"
            )
        else:
            full_prompt = f"{persona_section}{security_prefix}{message}"
        
        # Write prompt to a temp file to avoid shell escaping issues
        prompt_file = None
        try:
            # Create temp file with prompt
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(full_prompt)
                prompt_file = f.name
            
            # SECURITY: Set environment to restrict file access
            secure_env = os.environ.copy()
            secure_env['GEMINI_MCP_ALLOWED_DIRS'] = self.ALLOWED_DIR
            
            # Build command - simple piping approach (same as what worked yesterday)
            # Note: MCP servers may not fully load in subprocess mode, but google-workspace
            # extension basic functions (like creating docs) still work
            if use_mcp:
                # Include MCP server whitelist for security
                allowed_servers_flags = ' '.join(
                    f'--allowed-mcp-server-names {server}' for server in self.ALLOWED_MCP_SERVERS
                )
                gemini_cmd = (
                    f'type "{prompt_file}" | {self._get_gemini_cmd()} '
                    f'{allowed_servers_flags} '
                    f'--yolo'
                )
            else:
                # Fast mode: No MCP servers, just pure LLM processing
                # Used for simple tasks like JSON extraction where tools aren't needed
                gemini_cmd = (
                    f'type "{prompt_file}" | {self._get_gemini_cmd()} '
                    f'--yolo'
                )
            
            logger.debug(f"Gemini command: {gemini_cmd}")
            
            process = await asyncio.create_subprocess_shell(
                gemini_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.ALLOWED_DIR,
                env=secure_env
            )
            
            self.current_process = process
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                self.cancel_current()
                raise TimeoutError(
                    f"Gemini CLI did not respond within {self.timeout} seconds"
                )
            
            self.current_process = None
            
            # Decode output
            output = stdout.decode('utf-8', errors='replace').strip()
            error_output = stderr.decode('utf-8', errors='replace').strip()
            
            # Log for debugging
            logger.debug(f"Gemini stdout: {output[:200] if output else '(empty)'}")
            logger.debug(f"Gemini stderr: {error_output[:200] if error_output else '(empty)'}")
            
            if process.returncode != 0 and not output:
                if error_output:
                    raise RuntimeError(f"Gemini CLI error: {error_output}")
                raise RuntimeError(f"Gemini CLI exited with code {process.returncode}")
            
            # Clean up the output (remove ANSI codes, etc.)
            output = self._clean_output(output)
            
            if not output and error_output:
                # Sometimes output goes to stderr
                output = self._clean_output(error_output)
            
            logger.debug(f"Received response ({len(output)} chars)")
            return output if output else "(No response from Gemini)"
            
        except TimeoutError:
            raise
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error calling Gemini CLI: {e}")
            raise RuntimeError(f"Failed to communicate with Gemini CLI: {e}")
        finally:
            # Clean up temp file
            if prompt_file and os.path.exists(prompt_file):
                try:
                    os.unlink(prompt_file)
                except:
                    pass
    
    def _escape_message(self, message: str) -> str:
        """Escape a message for safe shell execution.
        
        Args:
            message: The message to escape
            
        Returns:
            Escaped message safe for shell
        """
        # Escape double quotes and backslashes for Windows shell
        return message.replace('\\', '\\\\').replace('"', '\\"')
    
    def _clean_output(self, output: str) -> str:
        """Clean ANSI escape codes and other artifacts from output.
        
        Args:
            output: Raw output from Gemini CLI
            
        Returns:
            Cleaned output string
        """
        import re
        
        # Remove ANSI escape codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        output = ansi_escape.sub('', output)
        
        # Remove other control characters (except newlines and tabs)
        output = ''.join(
            char for char in output 
            if char >= ' ' or char in '\n\t'
        )
        
        return output.strip()
    
    def cancel_current(self) -> None:
        """Cancel the current running Gemini CLI process if any."""
        if self.current_process:
            try:
                self.current_process.terminate()
                logger.info("Terminated current Gemini CLI process")
            except Exception as e:
                logger.warning(f"Error terminating process: {e}")
            finally:
                self.current_process = None
