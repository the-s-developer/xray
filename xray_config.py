# xray_config.py

import os
import yaml
import re

def expand_env(val):
    if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
        return os.getenv(val[2:-1], "")
    return val

def deep_expand_env(cfg):
    if isinstance(cfg, dict):
        return {k: deep_expand_env(v) for k, v in cfg.items()}
    elif isinstance(cfg, list):
        return [deep_expand_env(i) for i in cfg]
    else:
        return expand_env(cfg)

def load_xray_config():
    with open("xray_config.yaml", "r", encoding="utf-8") as f:
        yaml_str = f.read()
    # ${VAR} ile tanımlı alanları env ile değiştir
    def env_replace(match):
        var = match.group(1)
        return os.environ.get(var, "")
    # Tüm ${VAR}'ları değiştir
    yaml_str = re.sub(r"\$\{(\w+)\}", env_replace, yaml_str)
    return yaml.safe_load(yaml_str)

def get_db_config(cfg=None, config_path=None):
    """Config içinden mongo_uri ve db_name çek."""
    if cfg is None:
        cfg = load_xray_config(config_path)
    xray_cfg = cfg.get("xray", {})
    mongo_uri = xray_cfg.get("mongo_uri", "mongodb://localhost:27017")
    db_name = xray_cfg.get("db_name", "xray")
    return mongo_uri, db_name

def get_model_config(config_id, models):
    """Config içinden id ile modeli bulur."""
    for model in models:
        if model.get("id") == config_id:
            model["enable_tools"] = model.get("enable_tools", True)
            return model
    raise ValueError(f"Model config bulunamadı: {config_id}")


def get_tool_config(tool_id, cfg=None, config_path=None):
    if cfg is None:
        cfg = load_xray_config(config_path)
    for t in cfg.get("tools", []):
        if t["id"] == tool_id:
            return t
    raise ValueError(f"Tool {tool_id} not found in config.")

def build_tool_from_config(conf):
    """Tool tipine göre doğru tool nesnesini hazırla."""
    if conf["type"] == "stdio":
        from tool_stdio_client import ToolStdioClient
        return ToolStdioClient(server_id=conf["id"], command=conf["command"], args=conf.get("args", []))
    if conf["type"] == "websocket":
        from tool_websocket_client import ToolWebSocketClient
        return ToolWebSocketClient(server_id=conf["id"], ws_url=conf["url"])
    raise NotImplementedError(f"Tool type {conf['type']} not implemented: {conf}")

