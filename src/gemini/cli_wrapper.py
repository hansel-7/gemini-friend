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
    ALLOWED_DIR = str(settings.DATA_DIR)
    
    # SECURITY: Only these MCP servers are allowed to run
    # - filesystem: local file access (restricted to ALLOWED_DIR)
    # - google-workspace: Google Workspace (Docs, Sheets, Drive, Gmail, Calendar) via extension
    # - playwright: web automation
    ALLOWED_MCP_SERVERS = ["filesystem", "google-workspace", "playwright"]
    
    # Gemini CLI command - prefer local project install, then npx fallback
    _GEMINI_LOCAL_CMD = Path("node_modules/.bin/gemini.cmd").resolve()
    
    # Singleton instance
    _instance: 'GeminiCLI' = None
    
    @classmethod
    def get_instance(cls) -> 'GeminiCLI':
        """Get the singleton GeminiCLI instance.
        
        All consumers should use this instead of GeminiCLI() directly
        to share one instance across the entire application.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def _get_gemini_cmd(cls) -> str:
        """Get the Gemini CLI command, preferring local project install."""
        # 1. Try local node_modules (best for portability/reproducibility)
        if cls._GEMINI_LOCAL_CMD.exists():
            return f'"{cls._GEMINI_LOCAL_CMD}"'
        # 2. Fallback to npx
        return 'npx @google/gemini-cli'
    
    # Persona configuration file
    PERSONA_FILE = str(settings.DATA_DIR / "persona.txt")
    
    def __init__(self):
        """Initialize the Gemini CLI wrapper."""
        self._active_processes: set = set()
        self.timeout = settings.GEMINI_TIMEOUT
        self._persona: Optional[str] = None
        self._capabilities: Optional[str] = None
        self._setup_gemini_config()
        self._load_persona()
        self._load_capabilities()
    
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
    
    def _load_capabilities(self) -> None:
        """Load capabilities manifest from config file.
        
        Reads config/capabilities.json and builds a formatted prompt section
        that tells Gemini what the bot can do, so it can proactively suggest
        relevant actions to the user.
        """
        try:
            config_path = Path(__file__).parent.parent.parent / 'config' / 'capabilities.json'
            if not config_path.exists():
                logger.info(f"No capabilities manifest found at {config_path}")
                self._capabilities = None
                return
            
            with open(config_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            
            # Build the formatted capabilities section
            instruction = manifest.get('instruction', '')
            capabilities = manifest.get('capabilities', [])
            
            if not capabilities:
                self._capabilities = None
                return
            
            lines = []
            lines.append(f"=== YOUR BOT CAPABILITIES ===")
            lines.append(instruction)
            lines.append("")
            
            for i, cap in enumerate(capabilities, 1):
                name = cap.get('name', 'Unknown')
                desc = cap.get('description', '')
                triggers = cap.get('triggers', [])
                examples = cap.get('examples', [])
                commands = cap.get('commands', [])
                
                lines.append(f"{i}. {name}: {desc}")
                if commands:
                    lines.append(f"   Commands: {', '.join(commands)}")
                if triggers:
                    lines.append(f"   Suggest when: {'; '.join(triggers)}")
                if examples:
                    lines.append(f"   Example suggestion: \"{examples[0]}\"")
                lines.append("")
            
            lines.append("IMPORTANT: Only suggest capabilities when genuinely relevant to the user's message. Don't list capabilities unprompted. Be natural and conversational.")
            lines.append("=== END CAPABILITIES ===\n")
            
            self._capabilities = '\n'.join(lines)
            logger.info(f"Loaded {len(capabilities)} capabilities from manifest")
            
        except Exception as e:
            logger.warning(f"Could not load capabilities manifest: {e}")
            self._capabilities = None
    
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
        
        # Build capabilities section (only for MCP-enabled requests)
        capabilities_section = ""
        if self._capabilities and use_mcp:
            capabilities_section = self._capabilities + "\n"
        
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
        
        # Build the full prompt with persona, capabilities, security, and context
        if context:
            full_prompt = (
                f"{persona_section}"
                f"{capabilities_section}"
                f"{security_prefix}"
                f"Previous conversation context:\n{context}\n\n"
                f"Current user message (respond to this): {message}"
            )
        else:
            full_prompt = f"{persona_section}{capabilities_section}{security_prefix}{message}"
        
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
            
            # Build command using -p/--prompt flag for non-interactive (headless) mode
            # Note: Gemini CLI v0.29+ defaults to interactive mode; must use -p flag.
            # We pass -p "" to trigger headless mode, and pipe the actual prompt via
            # stdin to avoid Windows command-line length limits (~32K chars).
            
            # Build the argument list for subprocess
            gemini_cmd_path = self._get_gemini_cmd().strip('"')
            cmd_args = [gemini_cmd_path]
            
            if use_mcp:
                # Include MCP server whitelist for security
                for server in self.ALLOWED_MCP_SERVERS:
                    cmd_args.extend(['--allowed-mcp-server-names', server])
            
            cmd_args.extend(['--yolo', '-p', ''])
            
            logger.debug(f"Gemini command: {gemini_cmd_path} -p '' [stdin prompt len={len(full_prompt)}]")
            
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.ALLOWED_DIR,
                env=secure_env
            )
            
            self._active_processes.add(process)
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=full_prompt.encode('utf-8')),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                except Exception:
                    pass
                self._active_processes.discard(process)
                raise TimeoutError(
                    f"Gemini CLI did not respond within {self.timeout} seconds"
                )
            
            self._active_processes.discard(process)
            
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
        """Cancel all active Gemini CLI processes."""
        if not self._active_processes:
            return
        
        count = len(self._active_processes)
        for process in list(self._active_processes):
            try:
                process.terminate()
            except Exception as e:
                logger.warning(f"Error terminating process: {e}")
        
        self._active_processes.clear()
        logger.info(f"Terminated {count} active Gemini CLI process(es)")
