# blender_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context, Image
import socket
import json
import asyncio
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List
import os
from pathlib import Path
import base64
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BlenderMCPServer")

@dataclass
class BlenderConnection:
    host: str
    port: int
    sock: socket.socket = None  # Changed from 'socket' to 'sock' to avoid naming conflict
    
    def connect(self) -> bool:
        """Connect to the Blender addon socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Blender at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Blender: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Blender addon"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Blender: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        # Use a consistent timeout value that matches the addon's timeout
        sock.settimeout(15.0)  # Match the addon's timeout
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        # If we get an empty chunk, the connection might be closed
                        if not chunks:  # If we haven't received anything yet, this is an error
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        # If we get here, it parsed successfully
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    # If we hit a timeout during receiving, break the loop and try to use what we have
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise  # Re-raise to be handled by the caller
        except socket.timeout:
            logger.warning("Socket timeout during chunked receive")
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        # Try to use what we have
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                # Try to parse what we have
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                # If we can't parse it, it's incomplete
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Blender and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Blender")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        try:
            # Log the command being sent
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # Set a timeout for receiving - use the same timeout as in receive_full_response
            self.sock.settimeout(15.0)  # Match the addon's timeout
            
            # Receive the response using the improved receive_full_response method
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Blender error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Blender"))
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Blender")
            # Don't try to reconnect here - let the get_blender_connection handle reconnection
            # Just invalidate the current socket so it will be recreated next time
            self.sock = None
            raise Exception("Timeout waiting for Blender response - try simplifying your request")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Blender lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Blender: {str(e)}")
            # Try to log what was received
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            raise Exception(f"Invalid response from Blender: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Blender: {str(e)}")
            # Don't try to reconnect here - let the get_blender_connection handle reconnection
            self.sock = None
            raise Exception(f"Communication error with Blender: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    # We don't need to create a connection here since we're using the global connection
    # for resources and tools
    
    try:
        # Just log that we're starting up
        logger.info("BlenderMCP server starting up")
        
        # Try to connect to Blender on startup to verify it's available
        try:
            # This will initialize the global connection if needed
            blender = get_blender_connection()
            logger.info("Successfully connected to Blender on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Blender on startup: {str(e)}")
            logger.warning("Make sure the Blender addon is running before using Blender resources or tools")
        
        # Return an empty context - we're using the global connection
        yield {}
    finally:
        # Clean up the global connection on shutdown
        global _blender_connection
        if _blender_connection:
            logger.info("Disconnecting from Blender on shutdown")
            _blender_connection.disconnect()
            _blender_connection = None
        logger.info("BlenderMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "BlenderMCP",
    description="Blender integration through the Model Context Protocol",
    lifespan=server_lifespan
)

# Resource endpoints

# Global connection for resources (since resources can't access context)
_blender_connection = None
_polyhaven_enabled = False  # Add this global variable

def get_blender_connection():
    """Get or create a persistent Blender connection"""
    global _blender_connection, _polyhaven_enabled  # Add _polyhaven_enabled to globals
    
    # If we have an existing connection, check if it's still valid
    if _blender_connection is not None:
        try:
            # First check if PolyHaven is enabled by sending a ping command
            result = _blender_connection.send_command("get_polyhaven_status")
            # Store the PolyHaven status globally
            _polyhaven_enabled = result.get("enabled", False)
            return _blender_connection
        except Exception as e:
            # Connection is dead, close it and create a new one
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _blender_connection.disconnect()
            except:
                pass
            _blender_connection = None
    
    # Create a new connection if needed
    if _blender_connection is None:
        _blender_connection = BlenderConnection(host="localhost", port=9876)
        if not _blender_connection.connect():
            logger.error("Failed to connect to Blender")
            _blender_connection = None
            raise Exception("Could not connect to Blender. Make sure the Blender addon is running.")
        logger.info("Created new persistent connection to Blender")
    
    return _blender_connection


@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Get detailed information about the current Blender scene"""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_scene_info")
        
        # Just return the JSON representation of what Blender sent us
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene info from Blender: {str(e)}")
        return f"Error getting scene info: {str(e)}"

@mcp.tool()
def get_object_info(ctx: Context, object_name: str) -> str:
    """
    Get detailed information about a specific object in the Blender scene.
    
    Parameters:
    - object_name: The name of the object to get information about
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_object_info", {"name": object_name})
        
        # Just return the JSON representation of what Blender sent us
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting object info from Blender: {str(e)}")
        return f"Error getting object info: {str(e)}"



@mcp.tool()
def execute_blender_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Blender. Make sure to do it step-by-step by breaking it into smaller chunks.
    
    Parameters:
    - code: The Python code to execute
    """
    try:
        # Get the global connection
        blender = get_blender_connection()
        
        result = blender.send_command("execute_code", {"code": code})
        return f"Code executed successfully: {result.get('result', '')}"
    except Exception as e:
        logger.error(f"Error executing code: {str(e)}")
        return f"Error executing code: {str(e)}"

@mcp.tool()
def get_polyhaven_categories(ctx: Context, asset_type: str = "hdris") -> str:
    """
    Get a list of categories for a specific asset type on Polyhaven.
    
    Parameters:
    - asset_type: The type of asset to get categories for (hdris, textures, models, all)
    """
    try:
        blender = get_blender_connection()
        if not _polyhaven_enabled:
            return "PolyHaven integration is disabled. Select it in the sidebar in BlenderMCP, then run it again."
        result = blender.send_command("get_polyhaven_categories", {"asset_type": asset_type})
        
        if "error" in result:
            return f"Error: {result['error']}"
        
        # Format the categories in a more readable way
        categories = result["categories"]
        formatted_output = f"Categories for {asset_type}:\n\n"
        
        # Sort categories by count (descending)
        sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        
        for category, count in sorted_categories:
            formatted_output += f"- {category}: {count} assets\n"
        
        return formatted_output
    except Exception as e:
        logger.error(f"Error getting Polyhaven categories: {str(e)}")
        return f"Error getting Polyhaven categories: {str(e)}"

@mcp.tool()
def search_polyhaven_assets(
    ctx: Context,
    asset_type: str = "all",
    categories: str = None
) -> str:
    """
    Search for assets on Polyhaven with optional filtering.
    
    Parameters:
    - asset_type: Type of assets to search for (hdris, textures, models, all)
    - categories: Optional comma-separated list of categories to filter by
    
    Returns a list of matching assets with basic information.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("search_polyhaven_assets", {
            "asset_type": asset_type,
            "categories": categories
        })
        
        if "error" in result:
            return f"Error: {result['error']}"
        
        # Format the assets in a more readable way
        assets = result["assets"]
        total_count = result["total_count"]
        returned_count = result["returned_count"]
        
        formatted_output = f"Found {total_count} assets"
        if categories:
            formatted_output += f" in categories: {categories}"
        formatted_output += f"\nShowing {returned_count} assets:\n\n"
        
        # Sort assets by download count (popularity)
        sorted_assets = sorted(assets.items(), key=lambda x: x[1].get("download_count", 0), reverse=True)
        
        for asset_id, asset_data in sorted_assets:
            formatted_output += f"- {asset_data.get('name', asset_id)} (ID: {asset_id})\n"
            formatted_output += f"  Type: {['HDRI', 'Texture', 'Model'][asset_data.get('type', 0)]}\n"
            formatted_output += f"  Categories: {', '.join(asset_data.get('categories', []))}\n"
            formatted_output += f"  Downloads: {asset_data.get('download_count', 'Unknown')}\n\n"
        
        return formatted_output
    except Exception as e:
        logger.error(f"Error searching Polyhaven assets: {str(e)}")
        return f"Error searching Polyhaven assets: {str(e)}"

@mcp.tool()
def download_polyhaven_asset(
    ctx: Context,
    asset_id: str,
    asset_type: str,
    resolution: str = "1k",
    file_format: str = None
) -> str:
    """
    Download and import a Polyhaven asset into Blender.
    
    Parameters:
    - asset_id: The ID of the asset to download
    - asset_type: The type of asset (hdris, textures, models)
    - resolution: The resolution to download (e.g., 1k, 2k, 4k)
    - file_format: Optional file format (e.g., hdr, exr for HDRIs; jpg, png for textures; gltf, fbx for models)
    
    Returns a message indicating success or failure.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("download_polyhaven_asset", {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "resolution": resolution,
            "file_format": file_format
        })
        
        if "error" in result:
            return f"Error: {result['error']}"
        
        if result.get("success"):
            message = result.get("message", "Asset downloaded and imported successfully")
            
            # Add additional information based on asset type
            if asset_type == "hdris":
                return f"{message}. The HDRI has been set as the world environment."
            elif asset_type == "textures":
                material_name = result.get("material", "")
                maps = ", ".join(result.get("maps", []))
                return f"{message}. Created material '{material_name}' with maps: {maps}."
            elif asset_type == "models":
                return f"{message}. The model has been imported into the current scene."
            else:
                return message
        else:
            return f"Failed to download asset: {result.get('message', 'Unknown error')}"
    except Exception as e:
        logger.error(f"Error downloading Polyhaven asset: {str(e)}")
        return f"Error downloading Polyhaven asset: {str(e)}"

@mcp.tool()
def set_texture(
    ctx: Context,
    object_name: str,
    texture_id: str
) -> str:
    """
    Apply a previously downloaded Polyhaven texture to an object.
    
    Parameters:
    - object_name: Name of the object to apply the texture to
    - texture_id: ID of the Polyhaven texture to apply (must be downloaded first)
    
    Returns a message indicating success or failure.
    """
    try:
        # Get the global connection
        blender = get_blender_connection()
        
        result = blender.send_command("set_texture", {
            "object_name": object_name,
            "texture_id": texture_id
        })
        
        if "error" in result:
            return f"Error: {result['error']}"
        
        if result.get("success"):
            material_name = result.get("material", "")
            maps = ", ".join(result.get("maps", []))
            
            # Add detailed material info
            material_info = result.get("material_info", {})
            node_count = material_info.get("node_count", 0)
            has_nodes = material_info.get("has_nodes", False)
            texture_nodes = material_info.get("texture_nodes", [])
            
            output = f"Successfully applied texture '{texture_id}' to {object_name}.\n"
            output += f"Using material '{material_name}' with maps: {maps}.\n\n"
            output += f"Material has nodes: {has_nodes}\n"
            output += f"Total node count: {node_count}\n\n"
            
            if texture_nodes:
                output += "Texture nodes:\n"
                for node in texture_nodes:
                    output += f"- {node['name']} using image: {node['image']}\n"
                    if node['connections']:
                        output += "  Connections:\n"
                        for conn in node['connections']:
                            output += f"    {conn}\n"
            else:
                output += "No texture nodes found in the material.\n"
            
            return output
        else:
            return f"Failed to apply texture: {result.get('message', 'Unknown error')}"
    except Exception as e:
        logger.error(f"Error applying texture: {str(e)}")
        return f"Error applying texture: {str(e)}"

@mcp.tool()
def get_polyhaven_status(ctx: Context) -> str:
    """
    Check if PolyHaven integration is enabled in Blender.
    Returns a message indicating whether PolyHaven features are available.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_polyhaven_status")
        enabled = result.get("enabled", False)
        message = result.get("message", "")
        
        return message
    except Exception as e:
        logger.error(f"Error checking PolyHaven status: {str(e)}")
        return f"Error checking PolyHaven status: {str(e)}"

@mcp.tool()
def get_hyper3d_status(ctx: Context) -> str:
    """
    Check if Hyper3D Rodin integration is enabled in Blender.
    Returns a message indicating whether Hyper3D Rodin features are available.

    Don't emphasize the key type in the returned message, but sliently remember it. 
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_hyper3d_status")
        enabled = result.get("enabled", False)
        message = result.get("message", "")
        if enabled:
            message += ""
        return message
    except Exception as e:
        logger.error(f"Error checking Hyper3D status: {str(e)}")
        return f"Error checking Hyper3D status: {str(e)}"


@mcp.tool()
def set_polyhaven_integration(ctx: Context, enabled: bool) -> str:
    """
    Enables or disables the Polyhaven integration in the Blender addon.
    This controls whether Polyhaven tools can be used. Check status with `get_polyhaven_status`.

    Example:
    To enable Polyhaven: `set_polyhaven_integration(enabled=True)`
    To disable Polyhaven: `set_polyhaven_integration(enabled=False)`

    Parameters:
    - enabled: Boolean value to enable (True) or disable (False) the integration.
    
    Returns:
    A JSON string indicating the outcome of the operation.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "set_integration_enabled",
            {"integration_name": "polyhaven", "enabled": enabled}
        )
        
        # The addon returns a dict with "status" and "message".
        # We'll use the message directly if success, or format an error string.
        if result.get("status") == "success":
            return result.get("message", "PolyHaven integration status updated successfully.")
        else:
            return f"Error updating PolyHaven integration: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in set_polyhaven_integration: {str(e)}")
        return f"Error setting PolyHaven integration: {str(e)}"

@mcp.tool()
def set_hyper3d_integration(ctx: Context, enabled: bool) -> str:
    """
    Enables or disables the Hyper3D integration in the Blender addon.
    This controls whether Hyper3D tools can be used. Check status with `get_hyper3d_status`.

    Example:
    To enable Hyper3D: `set_hyper3d_integration(enabled=True)`
    To disable Hyper3D: `set_hyper3d_integration(enabled=False)`

    Parameters:
    - enabled: Boolean value to enable (True) or disable (False) the integration.
    
    Returns:
    A JSON string indicating the outcome of the operation.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "set_integration_enabled",
            {"integration_name": "hyper3d", "enabled": enabled}
        )
        
        if result.get("status") == "success":
            return result.get("message", "Hyper3D integration status updated successfully.")
        else:
            return f"Error updating Hyper3D integration: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in set_hyper3d_integration: {str(e)}")
        return f"Error setting Hyper3D integration: {str(e)}"

def _process_bbox(original_bbox: list[float] | list[int] | None) -> list[int] | None:
    if original_bbox is None:
        return None
    if all(isinstance(i, int) for i in original_bbox):
        return original_bbox
    if any(i<=0 for i in original_bbox):
        raise ValueError("Incorrect number range: bbox must be bigger than zero!")
    return [int(float(i) / max(original_bbox) * 100) for i in original_bbox] if original_bbox else None

@mcp.tool()
def generate_hyper3d_model_via_text(
    ctx: Context,
    text_prompt: str,
    bbox_condition: list[float]=None
) -> str:
    """
    Generate 3D asset using Hyper3D by giving description of the desired asset, and import the asset into Blender.
    The 3D asset has built-in materials.
    The generated model has a normalized size, so re-scaling after generation can be useful.
    
    Parameters:
    - text_prompt: A short description of the desired model in **English**.
    - bbox_condition: Optional. If given, it has to be a list of floats of length 3. Controls the ratio between [Length, Width, Height] of the model.

    Returns a message indicating success or failure.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("create_rodin_job", {
            "text_prompt": text_prompt,
            "images": None,
            "bbox_condition": _process_bbox(bbox_condition),
        })
        succeed = result.get("submit_time", False)
        if succeed:
            return json.dumps({
                "task_uuid": result["uuid"],
                "subscription_key": result["jobs"]["subscription_key"],
            })
        else:
            return json.dumps(result)
    except Exception as e:
        logger.error(f"Error generating Hyper3D task: {str(e)}")
        return f"Error generating Hyper3D task: {str(e)}"

@mcp.tool()
def generate_hyper3d_model_via_images(
    ctx: Context,
    input_image_paths: list[str]=None,
    input_image_urls: list[str]=None,
    bbox_condition: list[float]=None
) -> str:
    """
    Generate 3D asset using Hyper3D by giving images of the wanted asset, and import the generated asset into Blender.
    The 3D asset has built-in materials.
    The generated model has a normalized size, so re-scaling after generation can be useful.
    
    Parameters:
    - input_image_paths: The **absolute** paths of input images. Even if only one image is provided, wrap it into a list. Required if Hyper3D Rodin in MAIN_SITE mode.
    - input_image_urls: The URLs of input images. Even if only one image is provided, wrap it into a list. Required if Hyper3D Rodin in FAL_AI mode.
    - bbox_condition: Optional. If given, it has to be a list of ints of length 3. Controls the ratio between [Length, Width, Height] of the model.

    Only one of {input_image_paths, input_image_urls} should be given at a time, depending on the Hyper3D Rodin's current mode.
    Returns a message indicating success or failure.
    """
    if input_image_paths is not None and input_image_urls is not None:
        return f"Error: Conflict parameters given!"
    if input_image_paths is None and input_image_urls is None:
        return f"Error: No image given!"
    if input_image_paths is not None:
        if not all(os.path.exists(i) for i in input_image_paths):
            return "Error: not all image paths are valid!"
        images = []
        for path in input_image_paths:
            with open(path, "rb") as f:
                images.append(
                    (Path(path).suffix, base64.b64encode(f.read()).decode("ascii"))
                )
    elif input_image_urls is not None:
        if not all(urlparse(i) for i in input_image_paths):
            return "Error: not all image URLs are valid!"
        images = input_image_urls.copy()
    try:
        blender = get_blender_connection()
        result = blender.send_command("create_rodin_job", {
            "text_prompt": None,
            "images": images,
            "bbox_condition": _process_bbox(bbox_condition),
        })
        succeed = result.get("submit_time", False)
        if succeed:
            return json.dumps({
                "task_uuid": result["uuid"],
                "subscription_key": result["jobs"]["subscription_key"],
            })
        else:
            return json.dumps(result)
    except Exception as e:
        logger.error(f"Error generating Hyper3D task: {str(e)}")
        return f"Error generating Hyper3D task: {str(e)}"

@mcp.tool()
def poll_rodin_job_status(
    ctx: Context,
    subscription_key: str=None,
    request_id: str=None,
):
    """
    Check if the Hyper3D Rodin generation task is completed.

    For Hyper3D Rodin mode MAIN_SITE:
        Parameters:
        - subscription_key: The subscription_key given in the generate model step.

        Returns a list of status. The task is done if all status are "Done".
        If "Failed" showed up, the generating process failed.
        This is a polling API, so only proceed if the status are finally determined ("Done" or "Canceled").

    For Hyper3D Rodin mode FAL_AI:
        Parameters:
        - request_id: The request_id given in the generate model step.

        Returns the generation task status. The task is done if status is "COMPLETED".
        The task is in progress if status is "IN_PROGRESS".
        If status other than "COMPLETED", "IN_PROGRESS", "IN_QUEUE" showed up, the generating process might be failed.
        This is a polling API, so only proceed if the status are finally determined ("COMPLETED" or some failed state).
    """
    try:
        blender = get_blender_connection()
        kwargs = {}
        if subscription_key:
            kwargs = {
                "subscription_key": subscription_key,
            }
        elif request_id:
            kwargs = {
                "request_id": request_id,
            }
        result = blender.send_command("poll_rodin_job_status", kwargs)
        return result
    except Exception as e:
        logger.error(f"Error generating Hyper3D task: {str(e)}")
        return f"Error generating Hyper3D task: {str(e)}"

@mcp.tool()
def import_generated_asset(
    ctx: Context,
    name: str,
    task_uuid: str=None,
    request_id: str=None,
):
    """
    Import the asset generated by Hyper3D Rodin after the generation task is completed.

    Parameters:
    - name: The name of the object in scene
    - task_uuid: For Hyper3D Rodin mode MAIN_SITE: The task_uuid given in the generate model step.
    - request_id: For Hyper3D Rodin mode FAL_AI: The request_id given in the generate model step.

    Only give one of {task_uuid, request_id} based on the Hyper3D Rodin Mode!
    Return if the asset has been imported successfully.
    """
    try:
        blender = get_blender_connection()
        kwargs = {
            "name": name
        }
        if task_uuid:
            kwargs["task_uuid"] = task_uuid
        elif request_id:
            kwargs["request_id"] = request_id
        result = blender.send_command("import_generated_asset", kwargs)
        return result
    except Exception as e:
        logger.error(f"Error generating Hyper3D task: {str(e)}")
        return f"Error generating Hyper3D task: {str(e)}"


@mcp.tool()
def add_geometry_node_modifier(ctx: Context, object_name: str, modifier_name: str = "GeometryNodes") -> str:
    """
        Adds a new Geometry Nodes modifier to the specified object in Blender.

        Example:
        To add a Geometry Nodes modifier to an object named "Cube":
        `add_geometry_node_modifier(object_name="Cube", modifier_name="MyGeoNodes")`

        Parameters:
        - object_name: The name of the Blender object to add the modifier to.
        - modifier_name: Optional name for the new modifier. Defaults to "GeometryNodes".
        
        Returns:
        A JSON string indicating success or failure and a message.
        """
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "add_geometry_node_modifier",
            {"object_name": object_name, "modifier_name": modifier_name}
        )
        
        # The addon already returns a dict with "status" and "message"
        if result.get("status") == "success":
            return result.get("message", "Geometry Nodes modifier added successfully.")
        else:
            return f"Error adding Geometry Nodes modifier: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in add_geometry_node_modifier: {str(e)}")
        return f"Error adding Geometry Nodes modifier: {str(e)}"

@mcp.tool()
def set_geometry_node_input(ctx: Context, object_name: str, modifier_name: str, input_name: str, value: Any) -> str:
    """
        Sets the value of a specified input within a Geometry Nodes modifier on an object.
        The input is identified by its name as it appears in the modifier's interface or node group.

        Example:
        If "Cube" has a Geometry Nodes modifier "MyGeoNodes" with an input named "Scale Factor":
        `set_geometry_node_input(object_name="Cube", modifier_name="MyGeoNodes", input_name="Scale Factor", value=1.5)`
        To set a vector input (e.g., for a Transform node):
        `set_geometry_node_input(object_name="Cube", modifier_name="MyGeoNodes", input_name="Translation", value=[1.0, 0.5, 0.0])`

        Parameters:
        - object_name: The name of the Blender object.
        - modifier_name: The name of the Geometry Nodes modifier.
        - input_name: The name (or identifier) of the input socket in the Geometry Node tree's interface.
        - value: The value to set for the input. Can be float, int, bool, or list of floats for vectors.
        
        Returns:
        A JSON string indicating success or failure and a message.
        """
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "set_geometry_node_input",
            {
                "object_name": object_name,
                "modifier_name": modifier_name,
                "input_name": input_name,
                "value": value
            }
        )
        
        if result.get("status") == "success":
            return result.get("message", f"Input '{input_name}' set successfully.")
        else:
            return f"Error setting Geometry Nodes input '{input_name}': {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in set_geometry_node_input: {str(e)}")
        return f"Error setting Geometry Nodes input: {str(e)}"

@mcp.tool()
def get_geometry_node_inputs(ctx: Context, object_name: str, modifier_name: str) -> str:
    """
        Retrieves a list of inputs from a Geometry Nodes modifier on a specified object.
        Each input includes its name, data type, and current value.

        Example:
        `get_geometry_node_inputs(object_name="Cube", modifier_name="MyGeoNodes")`

        Parameters:
        - object_name: The name of the Blender object.
        - modifier_name: The name of the Geometry Nodes modifier.
        
        Returns:
        A JSON string representing a list of dictionaries, each describing an input 
        (e.g., `[{"name": "Input_1", "type": "VALUE", "value": 0.5, "identifier": "Socket_001"}]`).
        """
    try:
        blender = get_blender_connection()
        result = blender.send_command(
            "get_geometry_node_inputs",
            {"object_name": object_name, "modifier_name": modifier_name}
        )
        
        # The addon returns a dict with "status", "inputs", etc.
        if result.get("status") == "success":
            inputs_list = result.get("inputs", [])
            if not inputs_list:
                return f"No inputs found for modifier '{modifier_name}' on object '{object_name}'."
            # Pretty-print the list of inputs
            return json.dumps(inputs_list, indent=2)
        else:
            return f"Error getting Geometry Nodes inputs: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in get_geometry_node_inputs: {str(e)}")
        return f"Error getting Geometry Nodes inputs: {str(e)}"


@mcp.tool()
def get_camera_info(ctx: Context, camera_name: str = None) -> str:
    """
    Retrieves information about a specified camera or the active scene camera.

    Example:
    `get_camera_info(camera_name="MyCamera")`
    `get_camera_info()` (for active scene camera)

    Parameters:
    - camera_name: Optional name of the camera. If None, uses the active scene camera.
    
    Returns:
    A JSON string with camera details (location, rotation, focal length, etc.).
    """
    try:
        blender = get_blender_connection()
        params = {}
        if camera_name:
            params["camera_name"] = camera_name
        
        result = blender.send_command("get_camera_info", params)
        
        # The addon returns a dict with "status" and "camera_info" or "message"
        if result.get("status") == "success" and "camera_info" in result:
            return json.dumps(result["camera_info"], indent=2)
        elif result.get("status") == "error":
            return f"Error from Blender: {result.get('message', 'Unknown error from addon.')}"
        else: # Should not happen if addon behaves as expected
            return json.dumps(result, indent=2) 
            
    except Exception as e:
        logger.error(f"Error in get_camera_info: {str(e)}")
        return f"Error getting camera info: {str(e)}"

@mcp.tool()
def set_camera_properties(ctx: Context, properties: Dict[str, Any], camera_name: str = None) -> str:
    """
    Sets properties for a specified camera or the active scene camera.

    Example:
    To set focal length:
    `set_camera_properties(properties={"lens": 50.0}, camera_name="MyCamera")`
    To set location:
    `set_camera_properties(properties={"location": [1.0, 2.0, 3.0]})` (for active scene camera)
    To set multiple properties for the active camera:
    `set_camera_properties(properties={"type": "ORTHO", "ortho_scale": 10.0, "clip_end": 500.0})`


    Parameters:
    - properties: Dictionary of properties to set (e.g., {"lens": 50, "location": [x,y,z]}). 
                  Valid keys include object properties like "location", "rotation_euler", "scale",
                  and camera data properties like "type", "lens" (or "focal_length"), "ortho_scale",
                  "sensor_width", "sensor_height", "sensor_fit", "clip_start", "clip_end",
                  "shift_x", "shift_y".
    - camera_name: Optional name of the camera. If None, uses the active scene camera.
    
    Returns:
    A JSON string indicating success or failure, and a message detailing applied/skipped properties.
    """
    try:
        blender = get_blender_connection()
        params = {"properties": properties}
        if camera_name:
            params["camera_name"] = camera_name
            
        result = blender.send_command("set_camera_properties", params)
        
        # The addon returns a dict with "status" and "message".
        if result.get("status") == "success":
            return result.get("message", "Camera properties update processed.")
        else:
            return f"Error setting camera properties: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in set_camera_properties: {str(e)}")
        return f"Error setting camera properties: {str(e)}"

@mcp.tool()
def create_camera(ctx: Context, camera_name: str, camera_type: str = 'PERSP', location: List[float] = None, rotation_euler: List[float] = None) -> str:
    """
    Creates a new camera in the Blender scene.

    Example:
    `create_camera(camera_name="NewViewCam", camera_type="PANO", location=[0, -10, 2], rotation_euler=[1.5708, 0, 0])`

    Parameters:
    - camera_name: Name for the new camera.
    - camera_type: Type of camera (e.g., 'PERSP', 'ORTHO', 'PANO'). Defaults to 'PERSP'.
    - location: Optional list of 3 floats for [X,Y,Z] location. Defaults to [0,0,0].
    - rotation_euler: Optional list of 3 floats for [X,Y,Z] Euler rotation in radians. Defaults to [0,0,0].
    
    Returns:
    A JSON string indicating success or failure.
    """
    # Handle default values for location and rotation_euler
    loc = location if location is not None else [0.0, 0.0, 0.0]
    rot = rotation_euler if rotation_euler is not None else [0.0, 0.0, 0.0]

    try:
        blender = get_blender_connection()
        params = {
            "camera_name": camera_name,
            "camera_type": camera_type,
            "location": loc,
            "rotation_euler": rot
        }
        result = blender.send_command("create_camera", params)
        
        if result.get("status") == "success":
            return result.get("message", f"Camera '{camera_name}' created successfully.")
        else:
            return f"Error creating camera: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in create_camera: {str(e)}")
        return f"Error creating camera: {str(e)}"

@mcp.tool()
def set_active_scene_camera(ctx: Context, camera_name: str) -> str:
    """
    Sets a camera as the active camera for the current scene.

    Example:
    `set_active_scene_camera(camera_name="MyCamera")`

    Parameters:
    - camera_name: The name of the camera to set as active.
    
    Returns:
    A JSON string indicating success or failure.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("set_active_scene_camera", {"camera_name": camera_name})
        
        if result.get("status") == "success":
            return result.get("message", f"Camera '{camera_name}' set as active scene camera.")
        else:
            return f"Error setting active scene camera: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in set_active_scene_camera: {str(e)}")
        return f"Error setting active scene camera: {str(e)}"


@mcp.tool()
def list_active_addons(ctx: Context) -> str:
    """
    Lists addons that Blender is currently aware of and has preferences for.
    This usually includes all enabled addons and any others that have been active.

    Example:
    `list_active_addons()`

    Returns:
    A JSON string listing addons with their name, ID (module name), and version.
    """
    try:
        blender = get_blender_connection()
        result = blender.send_command("list_active_addons") # No params needed
        
        if result.get("status") == "success" and "addons" in result:
            addons_list = result.get("addons", [])
            if not addons_list:
                return "No active addons found or reported by Blender."
            return json.dumps(addons_list, indent=2)
        elif result.get("status") == "error":
            return f"Error from Blender: {result.get('message', 'Unknown error from addon.')}"
        else:
            return json.dumps(result, indent=2) # Fallback for unexpected structure

    except Exception as e:
        logger.error(f"Error in list_active_addons: {str(e)}")
        return f"Error listing active addons: {str(e)}"

@mcp.tool()
def execute_addon_operator(ctx: Context, operator_name: str, operator_properties: Optional[Dict[str, Any]] = None) -> str:
    """
    Executes a Blender operator by its Python identifier string, optionally with properties.

    **CRITICAL WARNING:** This tool is EXPERIMENTAL and can lead to errors or Blender
    instability if misused. You MUST provide the exact, correct Blender operator name
    (e.g., "mesh.primitive_cube_add", not "bpy.ops.mesh.primitive_cube_add" unless that's how the addon registers it)
    and valid properties for that specific operator. Incorrect usage may crash Blender
    or produce unexpected results. Consult Blender's Python API or addon documentation
    for correct operator identifiers and properties.

    Example:
    To add a default cube: `execute_addon_operator(operator_name="mesh.primitive_cube_add")`
    To add a cube with specific properties:
    `execute_addon_operator(operator_name="mesh.primitive_cube_add", operator_properties={"size": 1.5, "location": [1,2,3]})`

    Parameters:
    - operator_name: The Python identifier string for the operator (e.g., "object.select_all").
    - operator_properties: Optional dictionary of properties to pass to the operator.
                           Property names and value types must exactly match the operator's requirements.
    
    Returns:
    A string message from Blender indicating the outcome, including operator result if successful.
    """
    op_props = operator_properties or {}
    try:
        blender = get_blender_connection()
        params = {
            "operator_name": operator_name,
            "operator_properties": op_props
        }
        result = blender.send_command("execute_addon_operator", params)
        
        # The addon returns a dict with "status", "message", and "operator_result".
        if result.get("status") == "success":
            return f"{result.get('message', 'Operator executed.')} Result: {result.get('operator_result', 'N/A')}"
        else:
            return f"Error executing operator: {result.get('message', 'Unknown error from addon.')}"
    except Exception as e:
        logger.error(f"Error in execute_addon_operator for '{operator_name}': {str(e)}")
        return f"Error executing operator '{operator_name}': {str(e)}"

@mcp.prompt()
def asset_creation_strategy() -> str:
    """Defines the preferred strategy for creating assets in Blender"""
    return """When creating 3D content in Blender, always start by checking if integrations are available:

    0. Before anything, always check the scene from get_scene_info()
    1. First use the following tools to verify if the following integrations are enabled:
        1. PolyHaven
            Use get_polyhaven_status() to verify its status
            If PolyHaven is enabled:
            - For objects/models: Use download_polyhaven_asset() with asset_type="models"
            - For materials/textures: Use download_polyhaven_asset() with asset_type="textures"
            - For environment lighting: Use download_polyhaven_asset() with asset_type="hdris"
        2. Hyper3D(Rodin)
            Hyper3D Rodin is good at generating 3D models for single item.
            So don't try to:
            1. Generate the whole scene with one shot
            2. Generate ground using Hyper3D
            3. Generate parts of the items separately and put them together afterwards

            Use get_hyper3d_status() to verify its status
            If Hyper3D is enabled:
            - For objects/models, do the following steps:
                1. Create the model generation task
                    - Use generate_hyper3d_model_via_images() if image(s) is/are given
                    - Use generate_hyper3d_model_via_text() if generating 3D asset using text prompt
                    If key type is free_trial and insufficient balance error returned, tell the user that the free trial key can only generated limited models everyday, they can choose to:
                    - Wait for another day and try again
                    - Go to hyper3d.ai to find out how to get their own API key
                    - Go to fal.ai to get their own private API key
                2. Poll the status
                    - Use poll_rodin_job_status() to check if the generation task has completed or failed
                3. Import the asset
                    - Use import_generated_asset() to import the generated GLB model the asset
                4. After importing the asset, ALWAYS check the world_bounding_box of the imported mesh, and adjust the mesh's location and size
                    Adjust the imported mesh's location, scale, rotation, so that the mesh is on the right spot.

                You can reuse assets previous generated by running python code to duplicate the object, without creating another generation task.

    3. Always check the world_bounding_box for each item so that:
        - Ensure that all objects that should not be clipping are not clipping.
        - Items have right spatial relationship.
    

    Only fall back to scripting when:
    - PolyHaven and Hyper3D are disabled
    - A simple primitive is explicitly requested
    - No suitable PolyHaven asset exists
    - Hyper3D Rodin failed to generate the desired asset
    - The task specifically requires a basic material/color
    """

# Main execution

def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()