# Code created by Siddharth Ahuja: www.github.com/ahujasid © 2025

import bpy
import mathutils
import json
import threading
import socket
import time
import requests
import tempfile
import traceback
import os
import shutil
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty
import io
from contextlib import redirect_stdout

bl_info = {
    "name": "Blender MCP",
    "author": "BlenderMCP",
    "version": (1, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > BlenderMCP",
    "description": "Connect Blender to Claude via MCP",
    "category": "Interface",
}

RODIN_FREE_TRIAL_KEY = "k9TcfFoEhNd9cCPP2guHAHHHkctZHIRhZDywZ1euGUXwihbYLpOjQhofby80NJez"

class BlenderMCPServer:
    def __init__(self, host='localhost', port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None
    
    def start(self):
        if self.running:
            print("Server is already running")
            return
            
        self.running = True
        
        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            
            # Start server thread
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            print(f"BlenderMCP server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start server: {str(e)}")
            self.stop()
            
    def stop(self):
        self.running = False
        
        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Wait for thread to finish
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except:
                pass
            self.server_thread = None
        
        print("BlenderMCP server stopped")
    
    def _server_loop(self):
        """Main server loop in a separate thread"""
        print("Server thread started")
        self.socket.settimeout(1.0)  # Timeout to allow for stopping
        
        while self.running:
            try:
                # Accept new connection
                try:
                    client, address = self.socket.accept()
                    print(f"Connected to client: {address}")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    # Just check running condition
                    continue
                except Exception as e:
                    print(f"Error accepting connection: {str(e)}")
                    time.sleep(0.5)
            except Exception as e:
                print(f"Error in server loop: {str(e)}")
                if not self.running:
                    break
                time.sleep(0.5)
        
        print("Server thread stopped")
    
    def _handle_client(self, client):
        """Handle connected client"""
        print("Client handler started")
        client.settimeout(None)  # No timeout
        buffer = b''
        
        try:
            while self.running:
                # Receive data
                try:
                    data = client.recv(8192)
                    if not data:
                        print("Client disconnected")
                        break
                    
                    buffer += data
                    try:
                        # Try to parse command
                        command = json.loads(buffer.decode('utf-8'))
                        buffer = b''
                        
                        # Execute command in Blender's main thread
                        def execute_wrapper():
                            try:
                                response = self.execute_command(command)
                                response_json = json.dumps(response)
                                try:
                                    client.sendall(response_json.encode('utf-8'))
                                except:
                                    print("Failed to send response - client disconnected")
                            except Exception as e:
                                print(f"Error executing command: {str(e)}")
                                traceback.print_exc()
                                try:
                                    error_response = {
                                        "status": "error",
                                        "message": str(e)
                                    }
                                    client.sendall(json.dumps(error_response).encode('utf-8'))
                                except:
                                    pass
                            return None
                        
                        # Schedule execution in main thread
                        bpy.app.timers.register(execute_wrapper, first_interval=0.0)
                    except json.JSONDecodeError:
                        # Incomplete data, wait for more
                        pass
                except Exception as e:
                    print(f"Error receiving data: {str(e)}")
                    break
        except Exception as e:
            print(f"Error in client handler: {str(e)}")
        finally:
            try:
                client.close()
            except:
                pass
            print("Client handler stopped")

    def execute_command(self, command):
        """Execute a command in the main Blender thread"""
        try:            
            return self._execute_command_internal(command)
                
        except Exception as e:
            print(f"Error executing command: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _execute_command_internal(self, command):
        """Internal command execution with proper context"""
        cmd_type = command.get("type")
        params = command.get("params", {})

        # Add a handler for checking PolyHaven status
        if cmd_type == "get_polyhaven_status":
            return {"status": "success", "result": self.get_polyhaven_status()}
        
        # Base handlers that are always available
        handlers = {
            "get_scene_info": self.get_scene_info,
            "get_object_info": self.get_object_info,
            "execute_code": self.execute_code,
            "get_polyhaven_status": self.get_polyhaven_status,
            "get_hyper3d_status": self.get_hyper3d_status,
            "add_geometry_node_modifier": self.add_geometry_node_modifier,
            "set_geometry_node_input": self.set_geometry_node_input,
            "get_geometry_node_inputs": self.get_geometry_node_inputs,
            "set_integration_enabled": self.set_integration_enabled,
            "get_camera_info": self.get_camera_info,
            "set_camera_properties": self.set_camera_properties,
            "create_camera": self.create_camera,
            "set_active_scene_camera": self.set_active_scene_camera,
            "list_active_addons": self.list_active_addons,
            "execute_addon_operator": self.execute_addon_operator,
        }
        
        # Add Polyhaven handlers only if enabled
        if bpy.context.scene.blendermcp_use_polyhaven:
            polyhaven_handlers = {
                "get_polyhaven_categories": self.get_polyhaven_categories,
                "search_polyhaven_assets": self.search_polyhaven_assets,
                "download_polyhaven_asset": self.download_polyhaven_asset,
                "set_texture": self.set_texture,
            }
            handlers.update(polyhaven_handlers)
        
        # Add Hyper3d handlers only if enabled
        if bpy.context.scene.blendermcp_use_hyper3d:
            polyhaven_handlers = {
                "create_rodin_job": self.create_rodin_job,
                "poll_rodin_job_status": self.poll_rodin_job_status,
                "import_generated_asset": self.import_generated_asset,
            }
            handlers.update(polyhaven_handlers)

        handler = handlers.get(cmd_type)
        if handler:
            try:
                print(f"Executing handler for {cmd_type}")
                result = handler(**params)
                print(f"Handler execution complete")
                return {"status": "success", "result": result}
            except Exception as e:
                print(f"Error in handler: {str(e)}")
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        else:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}

    
    
    def get_scene_info(self):
        """Get information about the current Blender scene"""
        try:
            print("Getting scene info...")
            # Simplify the scene info to reduce data size
            scene_info = {
                "name": bpy.context.scene.name,
                "object_count": len(bpy.context.scene.objects),
                "objects": [],
                "materials_count": len(bpy.data.materials),
            }
            
            # Collect minimal object information (limit to first 10 objects)
            for i, obj in enumerate(bpy.context.scene.objects):
                if i >= 10:  # Reduced from 20 to 10
                    break
                    
                obj_info = {
                    "name": obj.name,
                    "type": obj.type,
                    # Only include basic location data
                    "location": [round(float(obj.location.x), 2), 
                                round(float(obj.location.y), 2), 
                                round(float(obj.location.z), 2)],
                }
                scene_info["objects"].append(obj_info)
            
            print(f"Scene info collected: {len(scene_info['objects'])} objects")
            return scene_info
        except Exception as e:
            print(f"Error in get_scene_info: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}
    
    @staticmethod
    def _get_aabb(obj):
        """ Returns the world-space axis-aligned bounding box (AABB) of an object. """
        if obj.type != 'MESH':
            raise TypeError("Object must be a mesh")

        # Get the bounding box corners in local space
        local_bbox_corners = [mathutils.Vector(corner) for corner in obj.bound_box]

        # Convert to world coordinates
        world_bbox_corners = [obj.matrix_world @ corner for corner in local_bbox_corners]

        # Compute axis-aligned min/max coordinates
        min_corner = mathutils.Vector(map(min, zip(*world_bbox_corners)))
        max_corner = mathutils.Vector(map(max, zip(*world_bbox_corners)))

        return [
            [*min_corner], [*max_corner]
        ]


    
    def get_object_info(self, name):
        """Get detailed information about a specific object"""
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object not found: {name}")
        
        # Basic object info
        obj_info = {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            "visible": obj.visible_get(),
            "materials": [],
        }

        if obj.type == "MESH":
            bounding_box = self._get_aabb(obj)
            obj_info["world_bounding_box"] = bounding_box
        
        # Add material slots
        for slot in obj.material_slots:
            if slot.material:
                obj_info["materials"].append(slot.material.name)
        
        # Add mesh data if applicable
        if obj.type == 'MESH' and obj.data:
            mesh = obj.data
            obj_info["mesh"] = {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "polygons": len(mesh.polygons),
            }
        
        return obj_info
    
    def execute_code(self, code):
        """Execute arbitrary Blender Python code"""
        # This is powerful but potentially dangerous - use with caution
        try:
            # Create a local namespace for execution
            namespace = {"bpy": bpy}

            # Capture stdout during execution, and return it as result
            capture_buffer = io.StringIO()
            with redirect_stdout(capture_buffer):
                exec(code, namespace)
            
            captured_output = capture_buffer.getvalue()
            return {"executed": True, "result": captured_output}
        except Exception as e:
            raise Exception(f"Code execution error: {str(e)}")
    
    

    def get_polyhaven_categories(self, asset_type):
        """Get categories for a specific asset type from Polyhaven"""
        try:
            if asset_type not in ["hdris", "textures", "models", "all"]:
                return {"error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"}
                
            response = requests.get(f"https://api.polyhaven.com/categories/{asset_type}")
            if response.status_code == 200:
                return {"categories": response.json()}
            else:
                return {"error": f"API request failed with status code {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    def search_polyhaven_assets(self, asset_type=None, categories=None):
        """Search for assets from Polyhaven with optional filtering"""
        try:
            url = "https://api.polyhaven.com/assets"
            params = {}
            
            if asset_type and asset_type != "all":
                if asset_type not in ["hdris", "textures", "models"]:
                    return {"error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"}
                params["type"] = asset_type
                
            if categories:
                params["categories"] = categories
                
            response = requests.get(url, params=params)
            if response.status_code == 200:
                # Limit the response size to avoid overwhelming Blender
                assets = response.json()
                # Return only the first 20 assets to keep response size manageable
                limited_assets = {}
                for i, (key, value) in enumerate(assets.items()):
                    if i >= 20:  # Limit to 20 assets
                        break
                    limited_assets[key] = value
                
                return {"assets": limited_assets, "total_count": len(assets), "returned_count": len(limited_assets)}
            else:
                return {"error": f"API request failed with status code {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    def download_polyhaven_asset(self, asset_id, asset_type, resolution="1k", file_format=None):
        try:
            # First get the files information
            files_response = requests.get(f"https://api.polyhaven.com/files/{asset_id}")
            if files_response.status_code != 200:
                return {"error": f"Failed to get asset files: {files_response.status_code}"}
            
            files_data = files_response.json()
            
            # Handle different asset types
            if asset_type == "hdris":
                # For HDRIs, download the .hdr or .exr file
                if not file_format:
                    file_format = "hdr"  # Default format for HDRIs
                
                if "hdri" in files_data and resolution in files_data["hdri"] and file_format in files_data["hdri"][resolution]:
                    file_info = files_data["hdri"][resolution][file_format]
                    file_url = file_info["url"]
                    
                    # For HDRIs, we need to save to a temporary file first
                    # since Blender can't properly load HDR data directly from memory
                    with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                        # Download the file
                        response = requests.get(file_url)
                        if response.status_code != 200:
                            return {"error": f"Failed to download HDRI: {response.status_code}"}
                        
                        tmp_file.write(response.content)
                        tmp_path = tmp_file.name
                    
                    try:
                        # Create a new world if none exists
                        if not bpy.data.worlds:
                            bpy.data.worlds.new("World")
                        
                        world = bpy.data.worlds[0]
                        world.use_nodes = True
                        node_tree = world.node_tree
                        
                        # Clear existing nodes
                        for node in node_tree.nodes:
                            node_tree.nodes.remove(node)
                        
                        # Create nodes
                        tex_coord = node_tree.nodes.new(type='ShaderNodeTexCoord')
                        tex_coord.location = (-800, 0)
                        
                        mapping = node_tree.nodes.new(type='ShaderNodeMapping')
                        mapping.location = (-600, 0)
                        
                        # Load the image from the temporary file
                        env_tex = node_tree.nodes.new(type='ShaderNodeTexEnvironment')
                        env_tex.location = (-400, 0)
                        env_tex.image = bpy.data.images.load(tmp_path)
                        
                        # Use a color space that exists in all Blender versions
                        if file_format.lower() == 'exr':
                            # Try to use Linear color space for EXR files
                            try:
                                env_tex.image.colorspace_settings.name = 'Linear'
                            except:
                                # Fallback to Non-Color if Linear isn't available
                                env_tex.image.colorspace_settings.name = 'Non-Color'
                        else:  # hdr
                            # For HDR files, try these options in order
                            for color_space in ['Linear', 'Linear Rec.709', 'Non-Color']:
                                try:
                                    env_tex.image.colorspace_settings.name = color_space
                                    break  # Stop if we successfully set a color space
                                except:
                                    continue
                        
                        background = node_tree.nodes.new(type='ShaderNodeBackground')
                        background.location = (-200, 0)
                        
                        output = node_tree.nodes.new(type='ShaderNodeOutputWorld')
                        output.location = (0, 0)
                        
                        # Connect nodes
                        node_tree.links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
                        node_tree.links.new(mapping.outputs['Vector'], env_tex.inputs['Vector'])
                        node_tree.links.new(env_tex.outputs['Color'], background.inputs['Color'])
                        node_tree.links.new(background.outputs['Background'], output.inputs['Surface'])
                        
                        # Set as active world
                        bpy.context.scene.world = world
                        
                        # Clean up temporary file
                        try:
                            tempfile._cleanup()  # This will clean up all temporary files
                        except:
                            pass
                        
                        return {
                            "success": True, 
                            "message": f"HDRI {asset_id} imported successfully",
                            "image_name": env_tex.image.name
                        }
                    except Exception as e:
                        return {"error": f"Failed to set up HDRI in Blender: {str(e)}"}
                else:
                    return {"error": f"Requested resolution or format not available for this HDRI"}
                    
            elif asset_type == "textures":
                if not file_format:
                    file_format = "jpg"  # Default format for textures
                
                downloaded_maps = {}
                
                try:
                    for map_type in files_data:
                        if map_type not in ["blend", "gltf"]:  # Skip non-texture files
                            if resolution in files_data[map_type] and file_format in files_data[map_type][resolution]:
                                file_info = files_data[map_type][resolution][file_format]
                                file_url = file_info["url"]
                                
                                # Use NamedTemporaryFile like we do for HDRIs
                                with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                                    # Download the file
                                    response = requests.get(file_url)
                                    if response.status_code == 200:
                                        tmp_file.write(response.content)
                                        tmp_path = tmp_file.name
                                        
                                        # Load image from temporary file
                                        image = bpy.data.images.load(tmp_path)
                                        image.name = f"{asset_id}_{map_type}.{file_format}"
                                        
                                        # Pack the image into .blend file
                                        image.pack()
                                        
                                        # Set color space based on map type
                                        if map_type in ['color', 'diffuse', 'albedo']:
                                            try:
                                                image.colorspace_settings.name = 'sRGB'
                                            except:
                                                pass
                                        else:
                                            try:
                                                image.colorspace_settings.name = 'Non-Color'
                                            except:
                                                pass
                                        
                                        downloaded_maps[map_type] = image
                                        
                                        # Clean up temporary file
                                        try:
                                            os.unlink(tmp_path)
                                        except:
                                            pass
                
                    if not downloaded_maps:
                        return {"error": f"No texture maps found for the requested resolution and format"}
                    
                    # Create a new material with the downloaded textures
                    mat = bpy.data.materials.new(name=asset_id)
                    mat.use_nodes = True
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links
                    
                    # Clear default nodes
                    for node in nodes:
                        nodes.remove(node)
                    
                    # Create output node
                    output = nodes.new(type='ShaderNodeOutputMaterial')
                    output.location = (300, 0)
                    
                    # Create principled BSDF node
                    principled = nodes.new(type='ShaderNodeBsdfPrincipled')
                    principled.location = (0, 0)
                    links.new(principled.outputs[0], output.inputs[0])
                    
                    # Add texture nodes based on available maps
                    tex_coord = nodes.new(type='ShaderNodeTexCoord')
                    tex_coord.location = (-800, 0)
                    
                    mapping = nodes.new(type='ShaderNodeMapping')
                    mapping.location = (-600, 0)
                    mapping.vector_type = 'TEXTURE'  # Changed from default 'POINT' to 'TEXTURE'
                    links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])
                    
                    # Position offset for texture nodes
                    x_pos = -400
                    y_pos = 300
                    
                    # Connect different texture maps
                    for map_type, image in downloaded_maps.items():
                        tex_node = nodes.new(type='ShaderNodeTexImage')
                        tex_node.location = (x_pos, y_pos)
                        tex_node.image = image
                        
                        # Set color space based on map type
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            try:
                                tex_node.image.colorspace_settings.name = 'sRGB'
                            except:
                                pass  # Use default if sRGB not available
                        else:
                            try:
                                tex_node.image.colorspace_settings.name = 'Non-Color'
                            except:
                                pass  # Use default if Non-Color not available
                        
                        links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])
                        
                        # Connect to appropriate input on Principled BSDF
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                        elif map_type.lower() in ['roughness', 'rough']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                        elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                        elif map_type.lower() in ['normal', 'nor']:
                            # Add normal map node
                            normal_map = nodes.new(type='ShaderNodeNormalMap')
                            normal_map.location = (x_pos + 200, y_pos)
                            links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                            links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                        elif map_type in ['displacement', 'disp', 'height']:
                            # Add displacement node
                            disp_node = nodes.new(type='ShaderNodeDisplacement')
                            disp_node.location = (x_pos + 200, y_pos - 200)
                            links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                            links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])
                        
                        y_pos -= 250
                    
                    return {
                        "success": True, 
                        "message": f"Texture {asset_id} imported as material",
                        "material": mat.name,
                        "maps": list(downloaded_maps.keys())
                    }
                
                except Exception as e:
                    return {"error": f"Failed to process textures: {str(e)}"}
                
            elif asset_type == "models":
                # For models, prefer glTF format if available
                if not file_format:
                    file_format = "gltf"  # Default format for models
                
                if file_format in files_data and resolution in files_data[file_format]:
                    file_info = files_data[file_format][resolution][file_format]
                    file_url = file_info["url"]
                    
                    # Create a temporary directory to store the model and its dependencies
                    temp_dir = tempfile.mkdtemp()
                    main_file_path = ""
                    
                    try:
                        # Download the main model file
                        main_file_name = file_url.split("/")[-1]
                        main_file_path = os.path.join(temp_dir, main_file_name)
                        
                        response = requests.get(file_url)
                        if response.status_code != 200:
                            return {"error": f"Failed to download model: {response.status_code}"}
                        
                        with open(main_file_path, "wb") as f:
                            f.write(response.content)
                        
                        # Check for included files and download them
                        if "include" in file_info and file_info["include"]:
                            for include_path, include_info in file_info["include"].items():
                                # Get the URL for the included file - this is the fix
                                include_url = include_info["url"]
                                
                                # Create the directory structure for the included file
                                include_file_path = os.path.join(temp_dir, include_path)
                                os.makedirs(os.path.dirname(include_file_path), exist_ok=True)
                                
                                # Download the included file
                                include_response = requests.get(include_url)
                                if include_response.status_code == 200:
                                    with open(include_file_path, "wb") as f:
                                        f.write(include_response.content)
                                else:
                                    print(f"Failed to download included file: {include_path}")
                        
                        # Import the model into Blender
                        if file_format == "gltf" or file_format == "glb":
                            bpy.ops.import_scene.gltf(filepath=main_file_path)
                        elif file_format == "fbx":
                            bpy.ops.import_scene.fbx(filepath=main_file_path)
                        elif file_format == "obj":
                            bpy.ops.import_scene.obj(filepath=main_file_path)
                        elif file_format == "blend":
                            # For blend files, we need to append or link
                            with bpy.data.libraries.load(main_file_path, link=False) as (data_from, data_to):
                                data_to.objects = data_from.objects
                            
                            # Link the objects to the scene
                            for obj in data_to.objects:
                                if obj is not None:
                                    bpy.context.collection.objects.link(obj)
                        else:
                            return {"error": f"Unsupported model format: {file_format}"}
                        
                        # Get the names of imported objects
                        imported_objects = [obj.name for obj in bpy.context.selected_objects]
                        
                        return {
                            "success": True, 
                            "message": f"Model {asset_id} imported successfully",
                            "imported_objects": imported_objects
                        }
                    except Exception as e:
                        return {"error": f"Failed to import model: {str(e)}"}
                    finally:
                        # Clean up temporary directory
                        try:
                            shutil.rmtree(temp_dir)
                        except:
                            print(f"Failed to clean up temporary directory: {temp_dir}")
                else:
                    return {"error": f"Requested format or resolution not available for this model"}
                
            else:
                return {"error": f"Unsupported asset type: {asset_type}"}
                
        except Exception as e:
            return {"error": f"Failed to download asset: {str(e)}"}

    def set_texture(self, object_name, texture_id):
        """Apply a previously downloaded Polyhaven texture to an object by creating a new material"""
        try:
            # Get the object
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            
            # Make sure object can accept materials
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'materials'):
                return {"error": f"Object {object_name} cannot accept materials"}
            
            # Find all images related to this texture and ensure they're properly loaded
            texture_images = {}
            for img in bpy.data.images:
                if img.name.startswith(texture_id + "_"):
                    # Extract the map type from the image name
                    map_type = img.name.split('_')[-1].split('.')[0]
                    
                    # Force a reload of the image
                    img.reload()
                    
                    # Ensure proper color space
                    if map_type.lower() in ['color', 'diffuse', 'albedo']:
                        try:
                            img.colorspace_settings.name = 'sRGB'
                        except:
                            pass
                    else:
                        try:
                            img.colorspace_settings.name = 'Non-Color'
                        except:
                            pass
                    
                    # Ensure the image is packed
                    if not img.packed_file:
                        img.pack()
                    
                    texture_images[map_type] = img
                    print(f"Loaded texture map: {map_type} - {img.name}")
                    
                    # Debug info
                    print(f"Image size: {img.size[0]}x{img.size[1]}")
                    print(f"Color space: {img.colorspace_settings.name}")
                    print(f"File format: {img.file_format}")
                    print(f"Is packed: {bool(img.packed_file)}")

            if not texture_images:
                return {"error": f"No texture images found for: {texture_id}. Please download the texture first."}
            
            # Create a new material
            new_mat_name = f"{texture_id}_material_{object_name}"
            
            # Remove any existing material with this name to avoid conflicts
            existing_mat = bpy.data.materials.get(new_mat_name)
            if existing_mat:
                bpy.data.materials.remove(existing_mat)
            
            new_mat = bpy.data.materials.new(name=new_mat_name)
            new_mat.use_nodes = True
            
            # Set up the material nodes
            nodes = new_mat.node_tree.nodes
            links = new_mat.node_tree.links
            
            # Clear default nodes
            nodes.clear()
            
            # Create output node
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (600, 0)
            
            # Create principled BSDF node
            principled = nodes.new(type='ShaderNodeBsdfPrincipled')
            principled.location = (300, 0)
            links.new(principled.outputs[0], output.inputs[0])
            
            # Add texture nodes based on available maps
            tex_coord = nodes.new(type='ShaderNodeTexCoord')
            tex_coord.location = (-800, 0)
            
            mapping = nodes.new(type='ShaderNodeMapping')
            mapping.location = (-600, 0)
            mapping.vector_type = 'TEXTURE'  # Changed from default 'POINT' to 'TEXTURE'
            links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])
            
            # Position offset for texture nodes
            x_pos = -400
            y_pos = 300
            
            # Connect different texture maps
            for map_type, image in texture_images.items():
                tex_node = nodes.new(type='ShaderNodeTexImage')
                tex_node.location = (x_pos, y_pos)
                tex_node.image = image
                
                # Set color space based on map type
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    try:
                        tex_node.image.colorspace_settings.name = 'sRGB'
                    except:
                        pass  # Use default if sRGB not available
                else:
                    try:
                        tex_node.image.colorspace_settings.name = 'Non-Color'
                    except:
                        pass  # Use default if Non-Color not available
                
                links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])
                
                # Connect to appropriate input on Principled BSDF
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                elif map_type.lower() in ['roughness', 'rough']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                elif map_type.lower() in ['normal', 'nor', 'dx', 'gl']:
                    # Add normal map node
                    normal_map = nodes.new(type='ShaderNodeNormalMap')
                    normal_map.location = (x_pos + 200, y_pos)
                    links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                    links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                elif map_type.lower() in ['displacement', 'disp', 'height']:
                    # Add displacement node
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (x_pos + 200, y_pos - 200)
                    disp_node.inputs['Scale'].default_value = 0.1  # Reduce displacement strength
                    links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])
                
                y_pos -= 250
            
            # Second pass: Connect nodes with proper handling for special cases
            texture_nodes = {}
            
            # First find all texture nodes and store them by map type
            for node in nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    for map_type, image in texture_images.items():
                        if node.image == image:
                            texture_nodes[map_type] = node
                            break
            
            # Now connect everything using the nodes instead of images
            # Handle base color (diffuse)
            for map_name in ['color', 'diffuse', 'albedo']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Base Color'])
                    print(f"Connected {map_name} to Base Color")
                    break
            
            # Handle roughness
            for map_name in ['roughness', 'rough']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Roughness'])
                    print(f"Connected {map_name} to Roughness")
                    break
            
            # Handle metallic
            for map_name in ['metallic', 'metalness', 'metal']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Metallic'])
                    print(f"Connected {map_name} to Metallic")
                    break
            
            # Handle normal maps
            for map_name in ['gl', 'dx', 'nor']:
                if map_name in texture_nodes:
                    normal_map_node = nodes.new(type='ShaderNodeNormalMap')
                    normal_map_node.location = (100, 100)
                    links.new(texture_nodes[map_name].outputs['Color'], normal_map_node.inputs['Color'])
                    links.new(normal_map_node.outputs['Normal'], principled.inputs['Normal'])
                    print(f"Connected {map_name} to Normal")
                    break
            
            # Handle displacement
            for map_name in ['displacement', 'disp', 'height']:
                if map_name in texture_nodes:
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (300, -200)
                    disp_node.inputs['Scale'].default_value = 0.1  # Reduce displacement strength
                    links.new(texture_nodes[map_name].outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])
                    print(f"Connected {map_name} to Displacement")
                    break
            
            # Handle ARM texture (Ambient Occlusion, Roughness, Metallic)
            if 'arm' in texture_nodes:
                separate_rgb = nodes.new(type='ShaderNodeSeparateRGB')
                separate_rgb.location = (-200, -100)
                links.new(texture_nodes['arm'].outputs['Color'], separate_rgb.inputs['Image'])
                
                # Connect Roughness (G) if no dedicated roughness map
                if not any(map_name in texture_nodes for map_name in ['roughness', 'rough']):
                    links.new(separate_rgb.outputs['G'], principled.inputs['Roughness'])
                    print("Connected ARM.G to Roughness")
                
                # Connect Metallic (B) if no dedicated metallic map
                if not any(map_name in texture_nodes for map_name in ['metallic', 'metalness', 'metal']):
                    links.new(separate_rgb.outputs['B'], principled.inputs['Metallic'])
                    print("Connected ARM.B to Metallic")
                
                # For AO (R channel), multiply with base color if we have one
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break
                
                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% influence
                    
                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)
                    
                    # Connect through the mix node
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(separate_rgb.outputs['R'], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("Connected ARM.R to AO mix with Base Color")
            
            # Handle AO (Ambient Occlusion) if separate
            if 'ao' in texture_nodes:
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break
                
                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% influence
                    
                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)
                    
                    # Connect through the mix node
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(texture_nodes['ao'].outputs['Color'], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("Connected AO to mix with Base Color")
            
            # CRITICAL: Make sure to clear all existing materials from the object
            while len(obj.data.materials) > 0:
                obj.data.materials.pop(index=0)
            
            # Assign the new material to the object
            obj.data.materials.append(new_mat)
            
            # CRITICAL: Make the object active and select it
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            
            # CRITICAL: Force Blender to update the material
            bpy.context.view_layer.update()
            
            # Get the list of texture maps
            texture_maps = list(texture_images.keys())
            
            # Get info about texture nodes for debugging
            material_info = {
                "name": new_mat.name,
                "has_nodes": new_mat.use_nodes,
                "node_count": len(new_mat.node_tree.nodes),
                "texture_nodes": []
            }
            
            for node in new_mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    connections = []
                    for output in node.outputs:
                        for link in output.links:
                            connections.append(f"{output.name} → {link.to_node.name}.{link.to_socket.name}")
                    
                    material_info["texture_nodes"].append({
                        "name": node.name,
                        "image": node.image.name,
                        "colorspace": node.image.colorspace_settings.name,
                        "connections": connections
                    })
            
            return {
                "success": True,
                "message": f"Created new material and applied texture {texture_id} to {object_name}",
                "material": new_mat.name,
                "maps": texture_maps,
                "material_info": material_info
            }
            
        except Exception as e:
            print(f"Error in set_texture: {str(e)}")
            traceback.print_exc()
            return {"error": f"Failed to apply texture: {str(e)}"}

    def get_polyhaven_status(self):
        """Get the current status of PolyHaven integration"""
        enabled = bpy.context.scene.blendermcp_use_polyhaven
        if enabled:
            return {"enabled": True, "message": "PolyHaven integration is enabled and ready to use."}
        else:
            return {
                "enabled": False, 
                "message": """PolyHaven integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use assets from Poly Haven' checkbox
                            3. Restart the connection to Claude"""
        }

    #region Hyper3D
    def get_hyper3d_status(self):
        """Get the current status of Hyper3D Rodin integration"""
        enabled = bpy.context.scene.blendermcp_use_hyper3d
        if enabled:
            if not bpy.context.scene.blendermcp_hyper3d_api_key:
                return {
                    "enabled": False, 
                    "message": """Hyper3D Rodin integration is currently enabled, but API key is not given. To enable it:
                                1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                                2. Keep the 'Use Hyper3D Rodin 3D model generation' checkbox checked
                                3. Choose the right plaform and fill in the API Key
                                4. Restart the connection to Claude"""
                }
            mode = bpy.context.scene.blendermcp_hyper3d_mode
            message = f"Hyper3D Rodin integration is enabled and ready to use. Mode: {mode}. " + \
                f"Key type: {'private' if bpy.context.scene.blendermcp_hyper3d_api_key != RODIN_FREE_TRIAL_KEY else 'free_trial'}"
            return {
                "enabled": True,
                "message": message
            }
        else:
            return {
                "enabled": False, 
                "message": """Hyper3D Rodin integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use Hyper3D Rodin 3D model generation' checkbox
                            3. Restart the connection to Claude"""
            }

    def set_integration_enabled(self, integration_name: str, enabled: bool):
        """Enables or disables a specified integration."""
        try:
            if integration_name.lower() == "polyhaven":
                bpy.context.scene.blendermcp_use_polyhaven = enabled
                status_message = f"PolyHaven integration {'enabled' if enabled else 'disabled'}."
            elif integration_name.lower() == "hyper3d":
                bpy.context.scene.blendermcp_use_hyper3d = enabled
                status_message = f"Hyper3D integration {'enabled' if enabled else 'disabled'}."
            else:
                return {"status": "error", "message": f"Unknown integration name: {integration_name}"}
            
            return {"status": "success", "message": status_message}
        except Exception as e:
            # Log the exception for debugging
            print(f"Error in set_integration_enabled: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": f"Failed to set integration {integration_name}: {str(e)}"}

    def create_rodin_job(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.create_rodin_job_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.create_rodin_job_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def create_rodin_job_main_site(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            if images is None:
                images = []
            """Call Rodin API, get the job uuid and subscription key"""
            files = [
                *[("images", (f"{i:04d}{img_suffix}", img)) for i, (img_suffix, img) in enumerate(images)],
                ("tier", (None, "Sketch")),
                ("mesh_mode", (None, "Raw")),
            ]
            if text_prompt:
                files.append(("prompt", (None, text_prompt)))
            if bbox_condition:
                files.append(("bbox_condition", (None, json.dumps(bbox_condition))))
            response = requests.post(
                "https://hyperhuman.deemos.com/api/v2/rodin",
                headers={
                    "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
                },
                files=files
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}
    
    def create_rodin_job_fal_ai(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            req_data = {
                "tier": "Sketch",
            }
            if images:
                req_data["input_image_urls"] = images
            if text_prompt:
                req_data["prompt"] = text_prompt
            if bbox_condition:
                req_data["bbox_condition"] = bbox_condition
            response = requests.post(
                "https://queue.fal.run/fal-ai/hyper3d/rodin",
                headers={
                    "Authorization": f"Key {bpy.context.scene.blendermcp_hyper3d_api_key}",
                    "Content-Type": "application/json",
                },
                json=req_data
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}

    def poll_rodin_job_status(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.poll_rodin_job_status_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.poll_rodin_job_status_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def poll_rodin_job_status_main_site(self, subscription_key: str):
        """Call the job status API to get the job status"""
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/status",
            headers={
                "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
            json={
                "subscription_key": subscription_key,
            },
        )
        data = response.json()
        return {
            "status_list": [i["status"] for i in data["jobs"]]
        }
    
    def poll_rodin_job_status_fal_ai(self, request_id: str):
        """Call the job status API to get the job status"""
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}/status",
            headers={
                "Authorization": f"KEY {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
        )
        data = response.json()
        return data

    @staticmethod
    def _clean_imported_glb(filepath, mesh_name=None):
        # Get the set of existing objects before import
        existing_objects = set(bpy.data.objects)

        # Import the GLB file
        bpy.ops.import_scene.gltf(filepath=filepath)
        
        # Ensure the context is updated
        bpy.context.view_layer.update()
        
        # Get all imported objects
        imported_objects = list(set(bpy.data.objects) - existing_objects)
        # imported_objects = [obj for obj in bpy.context.view_layer.objects if obj.select_get()]
        
        if not imported_objects:
            print("Error: No objects were imported.")
            return
        
        # Identify the mesh object
        mesh_obj = None
        
        if len(imported_objects) == 1 and imported_objects[0].type == 'MESH':
            mesh_obj = imported_objects[0]
            print("Single mesh imported, no cleanup needed.")
        else:
            if len(imported_objects) == 2:
                empty_objs = [i for i in imported_objects if i.type == "EMPTY"]
                if len(empty_objs) != 1:
                    print("Error: Expected an empty node with one mesh child or a single mesh object.")
                    return
                parent_obj = empty_objs.pop()
                if len(parent_obj.children) == 1:
                    potential_mesh = parent_obj.children[0]
                    if potential_mesh.type == 'MESH':
                        print("GLB structure confirmed: Empty node with one mesh child.")
                        
                        # Unparent the mesh from the empty node
                        potential_mesh.parent = None
                        
                        # Remove the empty node
                        bpy.data.objects.remove(parent_obj)
                        print("Removed empty node, keeping only the mesh.")
                        
                        mesh_obj = potential_mesh
                    else:
                        print("Error: Child is not a mesh object.")
                        return
                else:
                    print("Error: Expected an empty node with one mesh child or a single mesh object.")
                    return
            else:
                print("Error: Expected an empty node with one mesh child or a single mesh object.")
                return
        
        # Rename the mesh if needed
        try:
            if mesh_obj and mesh_obj.name is not None and mesh_name:
                mesh_obj.name = mesh_name
                if mesh_obj.data.name is not None:
                    mesh_obj.data.name = mesh_name
                print(f"Mesh renamed to: {mesh_name}")
        except Exception as e:
            print("Having issue with renaming, give up renaming.")

        return mesh_obj

    def import_generated_asset(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.import_generated_asset_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.import_generated_asset_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def import_generated_asset_main_site(self, task_uuid: str, name: str):
        """Fetch the generated asset, import into blender"""
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/download",
            headers={
                "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
            json={
                'task_uuid': task_uuid
            }
        )
        data_ = response.json()
        temp_file = None
        for i in data_["list"]:
            if i["name"].endswith(".glb"):
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    prefix=task_uuid,
                    suffix=".glb",
                )
    
                try:
                    # Download the content
                    response = requests.get(i["url"], stream=True)
                    response.raise_for_status()  # Raise an exception for HTTP errors
                    
                    # Write the content to the temporary file
                    for chunk in response.iter_content(chunk_size=8192):
                        temp_file.write(chunk)
                        
                    # Close the file
                    temp_file.close()
                    
                except Exception as e:
                    # Clean up the file if there's an error
                    temp_file.close()
                    os.unlink(temp_file.name)
                    return {"succeed": False, "error": str(e)}
                
                break
        else:
            return {"succeed": False, "error": "Generation failed. Please first make sure that all jobs of the task are done and then try again later."}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box
            
            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}
    
    def import_generated_asset_fal_ai(self, request_id: str, name: str):
        """Fetch the generated asset, import into blender"""
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}",
            headers={
                "Authorization": f"Key {bpy.context.scene.blendermcp_hyper3d_api_key}",
            }
        )
        data_ = response.json()
        temp_file = None
        
        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            prefix=request_id,
            suffix=".glb",
        )

        try:
            # Download the content
            response = requests.get(data_["model_mesh"]["url"], stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors
            
            # Write the content to the temporary file
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
                
            # Close the file
            temp_file.close()
            
        except Exception as e:
            # Clean up the file if there's an error
            temp_file.close()
            os.unlink(temp_file.name)
            return {"succeed": False, "error": str(e)}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box
            
            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}

    def add_geometry_node_modifier(self, object_name: str, modifier_name: str = "GeometryNodes"):
        """Adds a Geometry Nodes modifier to the specified object."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"status": "error", "message": f"Object '{object_name}' not found."}

        try:
            modifier = obj.modifiers.new(name=modifier_name, type='NODES')
            return {
                "status": "success",
                "message": f"Geometry Nodes modifier '{modifier.name}' added to object '{object_name}'.",
                "object_name": object_name,
                "modifier_name": modifier.name
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to add Geometry Nodes modifier: {str(e)}"}

    def set_geometry_node_input(self, object_name: str, modifier_name: str, input_name: str, value: any):
        """Sets an input value on a Geometry Nodes modifier."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"status": "error", "message": f"Object '{object_name}' not found."}

        modifier = obj.modifiers.get(modifier_name)
        if not modifier or modifier.type != 'NODES':
            return {"status": "error", "message": f"Geometry Nodes modifier '{modifier_name}' not found on object '{object_name}'."}

        node_group = modifier.node_group
        if not node_group:
            # This can happen if the modifier was just added and no node group is assigned yet.
            # Create a new node group for it.
            try:
                node_group = bpy.data.node_groups.new(name=f"{object_name}_{modifier_name}_Nodes", type='GeometryNodeTree')
                modifier.node_group = node_group
                # Add default Group Input and Group Output nodes
                group_input_node = node_group.nodes.new('NodeGroupInput')
                group_input_node.location = (-200, 0)
                group_output_node = node_group.nodes.new('NodeGroupOutput')
                group_output_node.location = (200, 0)
                node_group.links.new(group_input_node.outputs['Geometry'], group_output_node.inputs['Geometry'])
            except Exception as e:
                 return {"status": "error", "message": f"Failed to create or assign node group for modifier '{modifier_name}': {str(e)}"}


        socket_input = None
        # Iterate over node_group.inputs, which are the sockets on the Group Input node
        for item in node_group.inputs:
            if item.name == input_name: # In modern Blender, use 'name' not 'identifier' for comparison
                socket_input = item
                break
        
        if not socket_input:
             # If input is not found, try to find it in the Group Input node directly
            group_input_node = None
            for node in node_group.nodes:
                if node.type == 'GROUP_INPUT':
                    group_input_node = node
                    break
            
            if group_input_node:
                for inp in group_input_node.outputs: # Outputs of Group Input node are inputs to the modifier
                    if inp.name == input_name: # Check by name
                        # This means the input exists on the node but not on the modifier interface.
                        # This case is tricky as we can't directly set it via modifier[input_name]
                        # We need to set the default_value of the socket on the node_group's interface
                        # Check if it's exposed to the interface via node_group.inputs
                        if input_name in node_group.inputs:
                            socket_input = node_group.inputs[input_name]
                            break
                        else:
                            # If not exposed, we might need to create it or inform the user.
                            # For now, let's try to create/expose it if it makes sense.
                            # However, directly setting node.outputs[input_name].default_value is not standard.
                            # The standard way is via modifier[input_name] or node_group.inputs[input_name].default_value
                            return {"status": "error", "message": f"Input '{input_name}' found on Group Input node but not exposed to modifier interface. Please expose it first."}
            
            if not socket_input:
                 return {"status": "error", "message": f"Input '{input_name}' not found in Geometry Nodes modifier '{modifier_name}'."}


        try:
            socket_type = socket_input.type
            if socket_type == 'VECTOR':
                if isinstance(value, (list, tuple)) and len(value) == 3:
                    modifier[socket_input.identifier] = mathutils.Vector(value)
                else:
                    return {"status": "error", "message": f"Input '{input_name}' expects a Vector (list/tuple of 3 numbers), but received {type(value)}: {value}."}
            elif socket_type == 'INT':
                modifier[socket_input.identifier] = int(value)
            elif socket_type == 'FLOAT':
                modifier[socket_input.identifier] = float(value)
            elif socket_type == 'BOOLEAN':
                modifier[socket_input.identifier] = bool(value)
            elif socket_type == 'RGBA': # Color
                 if isinstance(value, (list, tuple)) and len(value) in [3, 4]:
                    modifier[socket_input.identifier] = mathutils.Color(value[:3]) if len(value) == 3 else mathutils.Color(value[:3]) # alpha is separate for some sockets or part of the list
                    # For RGBA, it's often a list/tuple of 4 floats (R,G,B,A)
                    if len(value) == 4: # Assuming value is [R,G,B,A]
                         modifier[socket_input.identifier] = value # Directly assign if it's a list of 4 floats
                    elif len(value) == 3: # Assuming value is [R,G,B], alpha defaults to 1
                         modifier[socket_input.identifier] = list(value) + [1.0]
                    else:
                        return {"status": "error", "message": f"Input '{input_name}' (Color) expects a list/tuple of 3 or 4 numbers."}

            elif socket_type == 'STRING':
                modifier[socket_input.identifier] = str(value)
            # Add more type checks as needed, e.g. Object, Collection, Material, Texture
            elif socket_type == 'OBJECT':
                if isinstance(value, str): # Assume string is object name
                    obj_val = bpy.data.objects.get(value)
                    if not obj_val:
                        return {"status": "error", "message": f"Object '{value}' provided for input '{input_name}' not found."}
                    modifier[socket_input.identifier] = obj_val
                elif value is None: # Allow unsetting an object input
                     modifier[socket_input.identifier] = None
                else: # TODO: Could also be bpy.types.Object if passed from internal script
                    return {"status": "error", "message": f"Input '{input_name}' expects an Object name (str) or None."}
            else:
                # For other types (GEOMETRY, COLLECTION, MATERIAL, IMAGE, etc.), direct assignment might work if `value` is correct type.
                # However, robust handling requires knowing what `value` format to expect for these.
                # For now, try direct assignment and catch errors.
                try:
                    modifier[socket_input.identifier] = value
                except TypeError:
                     return {"status": "error", "message": f"Input '{input_name}' has type '{socket_type}' which is not directly settable with value '{value}' of type {type(value)}. Or the input is not exposed on the modifier interface."}
                except Exception as e: # Catch any other assignment error
                    # Check if the input is actually available on the modifier itself
                    # sometimes node_group.inputs exists but modifier[identifier] does not
                    if socket_input.identifier not in modifier:
                         return {"status": "error", "message": f"Input '{input_name}' (identifier: {socket_input.identifier}) of type '{socket_type}' is defined in the node group but not exposed or settable on the modifier. Please ensure it is an output of the 'Group Input' node and its interface socket is correctly configured."}
                    return {"status": "error", "message": f"Failed to set input '{input_name}' of type '{socket_type}' with value '{value}': {str(e)}"}


            return {
                "status": "success",
                "message": f"Input '{input_name}' set on modifier '{modifier_name}' of object '{object_name}'.",
                "object_name": object_name,
                "modifier_name": modifier_name,
                "input_name": input_name,
                "new_value": value
            }
        except Exception as e:
            # More detailed error if input is not found in modifier's settable properties
            if input_name not in modifier:
                 return {"status": "error", "message": f"Input '{input_name}' (identifier: {socket_input.identifier}) not found in modifier's settable properties. It might be defined in the node group but not properly exposed to the modifier interface. Error: {str(e)}"}
            return {"status": "error", "message": f"Failed to set input '{input_name}': {str(e)}"}

    def get_geometry_node_inputs(self, object_name: str, modifier_name: str):
        """Gets all input values from a Geometry Nodes modifier."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"status": "error", "message": f"Object '{object_name}' not found."}

        modifier = obj.modifiers.get(modifier_name)
        if not modifier or modifier.type != 'NODES':
            return {"status": "error", "message": f"Geometry Nodes modifier '{modifier_name}' not found on object '{object_name}'."}

        node_group = modifier.node_group
        if not node_group:
            return {"status": "success", "inputs": [], "message": f"Modifier '{modifier_name}' has no node group assigned."} # Or error?

        inputs_info = []
        for item in node_group.inputs: # These are bpy.types.NodeSocketInterface* items
            input_data = {
                "name": item.name, # User-facing name in the UI
                "identifier": item.identifier, # Internal ID used for access modifier[identifier]
                "type": item.type,
                "description": item.description,
                "value": None
            }
            
            try:
                # Access the value through the modifier using the socket's identifier
                # This gets the *current* value, not necessarily the default_value if it's overridden
                # For "Input" sockets on a modifier, this is the way to get their current effective value.
                current_value = modifier[item.identifier]

                if isinstance(current_value, mathutils.Vector):
                    input_data["value"] = list(current_value)
                elif isinstance(current_value, mathutils.Color):
                     # Blender Color can be 3 or 4 components (RGB or RGBA)
                    input_data["value"] = list(current_value)
                elif isinstance(current_value, (bpy.types.Object, bpy.types.Material, bpy.types.Collection, bpy.types.Texture, bpy.types.Image)):
                    input_data["value"] = current_value.name if current_value else None
                elif type(current_value).__name__ == "bpy_prop_array": # For some arrays like int[3]
                     input_data["value"] = list(current_value)
                else: # float, int, bool, string
                    input_data["value"] = current_value
            except KeyError:
                # This can happen if the input socket is defined in the node tree's interface (node_group.inputs)
                # but is not actually exposed or settable on the modifier itself.
                # This could be due to its type (e.g. Geometry) or how the group is set up.
                # In this case, we can try to report its default_value from the socket definition.
                try:
                    default_value = item.default_value
                    if isinstance(default_value, mathutils.Vector):
                        input_data["value"] = list(default_value)
                    elif isinstance(default_value, mathutils.Color):
                        input_data["value"] = list(default_value)
                    # bpy.types.Object etc. for default_value is usually None or not set.
                    # If it were an object, item.default_value would hold the bpy.types.Object itself.
                    elif isinstance(default_value, (bpy.types.Object, bpy.types.Material, bpy.types.Collection, bpy.types.Texture, bpy.types.Image)):
                         input_data["value"] = default_value.name if default_value else None
                    elif type(default_value).__name__ == "bpy_prop_array":
                         input_data["value"] = list(default_value)
                    else:
                        input_data["value"] = default_value
                    input_data["note"] = "Value shown is the default_value from the node group interface as it's not directly readable from the modifier."
                except Exception as e_default:
                    input_data["value"] = f"Error retrieving default value: {str(e_default)}"
                    input_data["note"] = "Could not retrieve value from modifier or default_value from socket."

            except Exception as e:
                input_data["value"] = f"Error retrieving value: {str(e)}"
            
            inputs_info.append(input_data)

        return {
            "status": "success",
            "object_name": object_name,
            "modifier_name": modifier_name,
            "inputs": inputs_info
        }

    #region Camera Control
    def get_camera_info(self, camera_name: str = None):
        """Gets information about the specified camera or the active scene camera."""
        try:
            cam_obj = None
            if camera_name:
                cam_obj = bpy.data.objects.get(camera_name)
                if not cam_obj:
                    return {"status": "error", "message": f"Camera object '{camera_name}' not found."}
                if cam_obj.type != 'CAMERA':
                    return {"status": "error", "message": f"Object '{camera_name}' is not a camera (type is {cam_obj.type})."}
            else:
                cam_obj = bpy.context.scene.camera
                if not cam_obj:
                    return {"status": "error", "message": "No active camera in the scene and no camera_name provided."}

            cam_data = cam_obj.data
            if not isinstance(cam_data, bpy.types.Camera): # Should be redundant if cam_obj.type == 'CAMERA'
                 return {"status": "error", "message": f"Object '{cam_obj.name}' does not have valid camera data."}


            info = {
                "object_name": cam_obj.name,
                "location": list(cam_obj.location),
                "rotation_euler": [cam_obj.rotation_euler.x, cam_obj.rotation_euler.y, cam_obj.rotation_euler.z],
                "scale": list(cam_obj.scale),
                "camera_data": {
                    "type": cam_data.type,
                    "lens": cam_data.lens if cam_data.type == 'PERSP' else None,
                    "focal_length": cam_data.lens if cam_data.type == 'PERSP' else None, # Alias for lens
                    "ortho_scale": cam_data.ortho_scale if cam_data.type == 'ORTHO' else None,
                    "sensor_width": cam_data.sensor_width,
                    "sensor_height": cam_data.sensor_height,
                    "sensor_fit": cam_data.sensor_fit,
                    "clip_start": cam_data.clip_start,
                    "clip_end": cam_data.clip_end,
                    "shift_x": cam_data.shift_x,
                    "shift_y": cam_data.shift_y,
                }
            }
            return {"status": "success", "camera_info": info}
        except Exception as e:
            return {"status": "error", "message": f"Failed to get camera info: {str(e)}"}

    def set_camera_properties(self, properties: dict, camera_name: str = None):
        """Sets properties for the specified camera or the active scene camera."""
        try:
            cam_obj = None
            if camera_name:
                cam_obj = bpy.data.objects.get(camera_name)
                if not cam_obj:
                    return {"status": "error", "message": f"Camera object '{camera_name}' not found."}
                if cam_obj.type != 'CAMERA':
                    return {"status": "error", "message": f"Object '{camera_name}' is not a camera."}
            else:
                cam_obj = bpy.context.scene.camera
                if not cam_obj:
                    return {"status": "error", "message": "No active camera in the scene and no camera_name provided."}
            
            cam_data = cam_obj.data
            applied_properties = []
            skipped_properties = []

            for key, value in properties.items():
                try:
                    if key in ["location", "rotation_euler", "scale"]: # Object properties
                        if key == "location" and isinstance(value, (list, tuple)) and len(value) == 3:
                            cam_obj.location = mathutils.Vector(value)
                            applied_properties.append(key)
                        elif key == "rotation_euler" and isinstance(value, (list, tuple)) and len(value) == 3:
                            cam_obj.rotation_euler = mathutils.Euler(value, 'XYZ') # Assuming XYZ order
                            applied_properties.append(key)
                        elif key == "scale" and isinstance(value, (list, tuple)) and len(value) == 3:
                            cam_obj.scale = mathutils.Vector(value)
                            applied_properties.append(key)
                        else:
                            skipped_properties.append({key: f"Invalid value type or length for {key}. Expected list/tuple of 3 numbers."})
                    
                    # Camera data properties
                    elif key in ["type", "lens", "focal_length", "ortho_scale", "sensor_width", "sensor_height", "sensor_fit", "clip_start", "clip_end", "shift_x", "shift_y"]:
                        if key == "focal_length": # Alias for lens
                            key = "lens"
                        
                        if hasattr(cam_data, key):
                            setattr(cam_data, key, value)
                            applied_properties.append(f"data.{key}")
                        else:
                             skipped_properties.append({key: f"Property data.{key} not found on camera data."})
                    else:
                        skipped_properties.append({key: "Unknown camera property."})
                except (TypeError, ValueError) as e:
                    skipped_properties.append({key: f"Error setting property: {str(e)}"})
                except Exception as e:
                    skipped_properties.append({key: f"Unexpected error setting property: {str(e)}"})


            message = f"Camera '{cam_obj.name}' properties update attempt finished."
            if applied_properties:
                message += f" Applied: {', '.join(applied_properties)}."
            if skipped_properties:
                message += f" Skipped/Errors: {json.dumps(skipped_properties)}."

            return {"status": "success", "message": message, "applied": applied_properties, "skipped": skipped_properties}

        except Exception as e:
            return {"status": "error", "message": f"Failed to set camera properties: {str(e)}"}

    def create_camera(self, camera_name: str, camera_type: str = 'PERSP', location: list = (0,0,0), rotation_euler: list = (0,0,0)):
        """Creates a new camera in the scene."""
        try:
            if camera_name in bpy.data.objects:
                 return {"status": "error", "message": f"Object named '{camera_name}' already exists."}

            # Create new camera data
            new_cam_data = bpy.data.cameras.new(name=camera_name) # Name for the data block
            
            valid_types = ['PERSP', 'ORTHO', 'PANO']
            if camera_type.upper() not in valid_types:
                return {"status": "error", "message": f"Invalid camera_type: {camera_type}. Must be one of {valid_types}."}
            new_cam_data.type = camera_type.upper()

            # Create new camera object
            new_cam_obj = bpy.data.objects.new(name=camera_name, object_data=new_cam_data) # Name for the object

            if isinstance(location, (list, tuple)) and len(location) == 3:
                new_cam_obj.location = mathutils.Vector(location)
            else:
                 return {"status": "error", "message": "Invalid location format. Expected list/tuple of 3 numbers."}

            if isinstance(rotation_euler, (list, tuple)) and len(rotation_euler) == 3:
                new_cam_obj.rotation_euler = mathutils.Euler(rotation_euler, 'XYZ') # Assuming XYZ order
            else:
                return {"status": "error", "message": "Invalid rotation_euler format. Expected list/tuple of 3 numbers."}

            # Link to scene's active collection
            bpy.context.scene.collection.objects.link(new_cam_obj)
            
            return {
                "status": "success", 
                "message": f"Camera '{camera_name}' created successfully.",
                "camera_name": new_cam_obj.name,
                "location": list(new_cam_obj.location),
                "rotation_euler": list(new_cam_obj.rotation_euler)
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to create camera: {str(e)}"}

    def set_active_scene_camera(self, camera_name: str):
        """Sets the specified camera as the active camera for the scene."""
        try:
            cam_obj = bpy.data.objects.get(camera_name)
            if not cam_obj:
                return {"status": "error", "message": f"Camera object '{camera_name}' not found."}
            if cam_obj.type != 'CAMERA':
                return {"status": "error", "message": f"Object '{camera_name}' is not a camera."}
            
            bpy.context.scene.camera = cam_obj
            return {"status": "success", "message": f"Camera '{camera_name}' set as active scene camera."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to set active scene camera: {str(e)}"}

    #endregion

    #region Addon Control
    def list_active_addons(self):
        """Lists addons that Blender is aware of and has preferences for (usually active/enabled)."""
        try:
            active_addons_info = []
            # bpy.context.preferences.addons provides AddonPreferences objects
            for addon_prefs in bpy.context.preferences.addons.values():
                addon_info = {
                    "name": addon_prefs.name,
                    "id": addon_prefs.module,
                    "version": ".".join(map(str, addon_prefs.version)) if hasattr(addon_prefs, 'version') and addon_prefs.version else "N/A"
                }
                active_addons_info.append(addon_info)
            
            return {"status": "success", "addons": active_addons_info}
        except Exception as e:
            return {"status": "error", "message": f"Failed to list active addons: {str(e)}"}

    def execute_addon_operator(self, operator_name: str, operator_properties: dict = None):
        """Executes a Blender operator by its Python identifier string."""
        try:
            if not operator_name:
                return {"status": "error", "message": "Operator name cannot be empty."}

            # Clean up operator_name: remove "bpy.ops." if present
            if operator_name.startswith("bpy.ops."):
                operator_name_parts = operator_name[len("bpy.ops."):].split('.')
            else:
                operator_name_parts = operator_name.split('.')

            if len(operator_name_parts) != 2:
                return {"status": "error", "message": f"Invalid operator name format: '{operator_name}'. Expected 'context.operator_id' (e.g., 'mesh.primitive_cube_add')."}

            context_name, operator_id = operator_name_parts[0], operator_name_parts[1]

            op_group = getattr(bpy.ops, context_name)
            op_func = getattr(op_group, operator_id)

            if operator_properties is None:
                operator_properties = {}
            
            # Execute the operator
            # Some operators return a set, e.g. {'FINISHED'}, {'CANCELLED'}. Others might return None or other types.
            # We'll capture this but primarily focus on whether an exception occurred.
            result = op_func(**operator_properties) 
            
            return {
                "status": "success", 
                "message": f"Operator '{operator_name}' executed.",
                "operator_result": str(result) # Convert result to string as it can be a set.
            }
        except AttributeError as e:
            return {"status": "error", "message": f"Operator not found or invalid: {operator_name}. Details: {str(e)}"}
        except (TypeError, RuntimeError) as e: # TypeError for bad args, RuntimeError for context issues
            return {"status": "error", "message": f"Error executing operator '{operator_name}' with properties {operator_properties}. Details: {str(e)}"}
        except Exception as e:
            return {"status": "error", "message": f"An unexpected error occurred while executing operator '{operator_name}': {str(e)}"}

    #endregion

# Blender UI Panel
class BLENDERMCP_PT_Panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "BLENDERMCP_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderMCP'
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        layout.prop(scene, "blendermcp_port")
        layout.prop(scene, "blendermcp_use_polyhaven", text="Use assets from Poly Haven")

        layout.prop(scene, "blendermcp_use_hyper3d", text="Use Hyper3D Rodin 3D model generation")
        if scene.blendermcp_use_hyper3d:
            layout.prop(scene, "blendermcp_hyper3d_mode", text="Rodin Mode")
            layout.prop(scene, "blendermcp_hyper3d_api_key", text="API Key")
            layout.operator("blendermcp.set_hyper3d_free_trial_api_key", text="Set Free Trial API Key")
        
        if not scene.blendermcp_server_running:
            layout.operator("blendermcp.start_server", text="Connect to MCP server")
        else:
            layout.operator("blendermcp.stop_server", text="Disconnect from MCP server")
            layout.label(text=f"Running on port {scene.blendermcp_port}")

# Operator to set Hyper3D API Key
class BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey(bpy.types.Operator):
    bl_idname = "blendermcp.set_hyper3d_free_trial_api_key"
    bl_label = "Set Free Trial API Key"
    
    def execute(self, context):
        context.scene.blendermcp_hyper3d_api_key = RODIN_FREE_TRIAL_KEY
        context.scene.blendermcp_hyper3d_mode = 'MAIN_SITE'
        self.report({'INFO'}, "API Key set successfully!")
        return {'FINISHED'}

# Operator to start the server
class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Connect to Claude"
    bl_description = "Start the BlenderMCP server to connect with Claude"
    
    def execute(self, context):
        scene = context.scene
        
        # Create a new server instance
        if not hasattr(bpy.types, "blendermcp_server") or not bpy.types.blendermcp_server:
            bpy.types.blendermcp_server = BlenderMCPServer(port=scene.blendermcp_port)
        
        # Start the server
        bpy.types.blendermcp_server.start()
        scene.blendermcp_server_running = True
        
        return {'FINISHED'}

# Operator to stop the server
class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop the connection to Claude"
    bl_description = "Stop the connection to Claude"
    
    def execute(self, context):
        scene = context.scene
        
        # Stop the server if it exists
        if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
            bpy.types.blendermcp_server.stop()
            del bpy.types.blendermcp_server
        
        scene.blendermcp_server_running = False
        
        return {'FINISHED'}

# Registration functions
def register():
    bpy.types.Scene.blendermcp_port = IntProperty(
        name="Port",
        description="Port for the BlenderMCP server",
        default=9876,
        min=1024,
        max=65535
    )
    
    bpy.types.Scene.blendermcp_server_running = bpy.props.BoolProperty(
        name="Server Running",
        default=False
    )
    
    bpy.types.Scene.blendermcp_use_polyhaven = bpy.props.BoolProperty(
        name="Use Poly Haven",
        description="Enable Poly Haven asset integration",
        default=False
    )

    bpy.types.Scene.blendermcp_use_hyper3d = bpy.props.BoolProperty(
        name="Use Hyper3D Rodin",
        description="Enable Hyper3D Rodin generatino integration",
        default=False
    )

    bpy.types.Scene.blendermcp_hyper3d_mode = bpy.props.EnumProperty(
        name="Rodin Mode",
        description="Choose the platform used to call Rodin APIs",
        items=[
            ("MAIN_SITE", "hyper3d.ai", "hyper3d.ai"),
            ("FAL_AI", "fal.ai", "fal.ai"),
        ],
        default="MAIN_SITE"
    )

    bpy.types.Scene.blendermcp_hyper3d_api_key = bpy.props.StringProperty(
        name="Hyper3D API Key",
        subtype="PASSWORD",
        description="API Key provided by Hyper3D",
        default=""
    )
    
    bpy.utils.register_class(BLENDERMCP_PT_Panel)
    bpy.utils.register_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.register_class(BLENDERMCP_OT_StartServer)
    bpy.utils.register_class(BLENDERMCP_OT_StopServer)
    
    print("BlenderMCP addon registered")

def unregister():
    # Stop the server if it's running
    if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
        bpy.types.blendermcp_server.stop()
        del bpy.types.blendermcp_server
    
    bpy.utils.unregister_class(BLENDERMCP_PT_Panel)
    bpy.utils.unregister_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.unregister_class(BLENDERMCP_OT_StartServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_StopServer)
    
    del bpy.types.Scene.blendermcp_port
    del bpy.types.Scene.blendermcp_server_running
    del bpy.types.Scene.blendermcp_use_polyhaven
    del bpy.types.Scene.blendermcp_use_hyper3d
    del bpy.types.Scene.blendermcp_hyper3d_mode
    del bpy.types.Scene.blendermcp_hyper3d_api_key

    print("BlenderMCP addon unregistered")

if __name__ == "__main__":
    register()
