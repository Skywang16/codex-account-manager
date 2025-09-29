#!/usr/bin/env python3
"""
Codex CLI 用量查询模块 - 简化版本
"""

import json
import glob
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional


class CodexUsageChecker:
    """Codex CLI 用量检查器"""
    
    def __init__(self, usage_cache_dir=None):
        """初始化用量检查器"""
        self.codex_sessions_dir = Path.home() / ".codex" / "sessions"
        
        # 用量缓存目录
        if usage_cache_dir:
            self.usage_cache_dir = Path(usage_cache_dir)
        else:
            current_dir = Path.cwd()
            if "codex-account-manager" in str(current_dir):
                project_dir = current_dir if current_dir.name == "codex-account-manager" else current_dir / "codex-account-manager"
                self.usage_cache_dir = project_dir / "codex-config" / "usage_cache"
            else:
                self.usage_cache_dir = Path.home() / ".codex" / "usage_cache"
        
        self.usage_cache_dir.mkdir(parents=True, exist_ok=True)
    
    def find_latest_session_file(self) -> Optional[Path]:
        """查找最新的有用量数据的 session 文件"""
        if not self.codex_sessions_dir.exists():
            return None
        
        pattern = str(self.codex_sessions_dir / "**" / "rollout-*.jsonl")
        session_files = glob.glob(pattern, recursive=True)
        
        if not session_files:
            return None
        
        # 按修改时间排序，检查最近的文件
        session_files.sort(key=lambda x: Path(x).stat().st_mtime, reverse=True)
        
        for session_file in session_files[:10]:  # 只检查最近10个文件
            if self._has_token_count_data(Path(session_file)):
                return Path(session_file)
        
        return Path(session_files[0]) if session_files else None
    
    def _has_token_count_data(self, session_file: Path) -> bool:
        """检查 session 文件是否包含 token_count 数据"""
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                # 只读取最后几行来快速检查
                lines = f.readlines()
                for line in reversed(lines[-20:]):  # 检查最后20行
                    try:
                        data = json.loads(line.strip())
                        if data.get('payload', {}).get('type') == 'token_count':
                            return True
                    except json.JSONDecodeError:
                        continue
            return False
        except (OSError, IOError):
            return False
    
    def parse_session_file(self, session_file: Path) -> Optional[Dict]:
        """解析 session 文件，查找最新的 token_count 事件"""
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 从后往前查找最新的 token_count 事件
            for line in reversed(lines):
                try:
                    data = json.loads(line.strip())
                    payload = data.get('payload', {})
                    
                    if payload.get('type') == 'token_count' and 'rate_limits' in payload:
                        return data
                except json.JSONDecodeError:
                    continue
            
            return None
        except (OSError, IOError):
            return None
    
    def save_usage_data(self, email: str, usage_data: Dict) -> bool:
        """保存用量数据到缓存"""
        if not email:
            return False
        
        try:
            safe_email = email.replace('@', '_at_').replace('.', '_').replace('+', '_plus_')
            cache_file = self.usage_cache_dir / f"{safe_email}_usage.json"
            
            cache_data = {
                "email": email,
                "last_updated": datetime.now().isoformat(),
                "usage_data": usage_data
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            return True
        except (OSError, IOError):
            return False
    
    def load_usage_data(self, email: str) -> Optional[Dict]:
        """从缓存加载用量数据"""
        if not email:
            return None
        
        try:
            safe_email = email.replace('@', '_at_').replace('.', '_').replace('+', '_plus_')
            cache_file = self.usage_cache_dir / f"{safe_email}_usage.json"
            
            if not cache_file.exists():
                return None
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 检查数据是否过期（超过24小时）
            last_updated = datetime.fromisoformat(cache_data.get('last_updated', ''))
            if datetime.now() - last_updated > timedelta(hours=24):
                return None
            
            return cache_data.get('usage_data')
        except (OSError, IOError, json.JSONDecodeError, ValueError):
            return None
    
    def get_usage_summary(self, email: str = None) -> Dict:
        """获取用量摘要"""
        summary = {
            "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "checking...",
            "token_usage": {},
            "rate_limits": {},
            "errors": []
        }
        
        session_file = self.find_latest_session_file()
        if not session_file:
            summary["errors"].append("未找到 Codex CLI session 文件")
            summary["status"] = "failed"
            return summary
        
        token_data = self.parse_session_file(session_file)
        if not token_data:
            summary["errors"].append("未找到有效的用量数据，请先在当前账号下使用 codex 发送消息")
            summary["status"] = "failed"
            return summary
        
        # 提取数据
        payload = token_data.get('payload', {})
        info = payload.get('info')
        
        if info and isinstance(info, dict) and 'total_token_usage' in info:
            summary["token_usage"] = info['total_token_usage']
        
        if 'rate_limits' in payload:
            summary["rate_limits"] = payload['rate_limits']
        
        summary["status"] = "success"
        
        # 保存到缓存
        if email and summary["status"] == "success":
            self.save_usage_data(email, {
                "check_time": summary["check_time"],
                "token_usage": summary["token_usage"],
                "rate_limits": summary["rate_limits"]
            })
        
        return summary
    
    def format_usage_summary(self, summary: Dict) -> str:
        """格式化使用情况摘要为可读文本"""
        lines = [
            f"Codex CLI 用量查询",
            f"查询时间: {summary['check_time']}",
            f"状态: {summary['status']}",
            "-" * 50
        ]
        
        if summary["status"] == "failed":
            lines.extend([
                "❌ 查询失败:",
                *[f"  - {error}" for error in summary.get("errors", [])],
                "\n💡 提示:",
                "  - 请确保已经使用过 Codex CLI",
                "  - 尝试运行 'codex' 命令并发送一条消息"
            ])
            return "\n".join(lines)
        
        # Token 使用情况
        if summary.get("token_usage"):
            usage = summary["token_usage"]
            lines.extend([
                "\n📊 Token 使用情况:",
                f"  输入 tokens: {usage.get('input_tokens', 0):,}",
                f"  缓存 tokens: {usage.get('cached_input_tokens', 0):,}",
                f"  输出 tokens: {usage.get('output_tokens', 0):,}",
                f"  总计 tokens: {usage.get('total_tokens', 0):,}"
            ])
        
        # 速率限制
        if summary.get("rate_limits"):
            limits = summary["rate_limits"]
            lines.append("\n⏰ 速率限制:")
            
            for key, limit in limits.items():
                if isinstance(limit, dict):
                    used_percent = limit.get("used_percent", 0)
                    resets_in_seconds = limit.get("resets_in_seconds", 0)
                    window_minutes = limit.get("window_minutes", 0)
                    
                    reset_time = datetime.now() + timedelta(seconds=resets_in_seconds)
                    window_type = "5小时窗口" if window_minutes <= 330 else "周限制"
                    
                    lines.extend([
                        f"  🔄 {window_type}:",
                        f"    已使用: {used_percent:.1f}%",
                        f"    重置时间: {reset_time.strftime('%H:%M:%S')}"
                    ])
        
        return "\n".join(lines)


def extract_email_from_auth(auth_data: Dict) -> Optional[str]:
    """从认证数据中提取邮箱地址"""
    try:
        import base64
        id_token = auth_data.get("tokens", {}).get("id_token", "")
        if id_token:
            parts = id_token.split(".")
            if len(parts) >= 2:
                payload = parts[1]
                payload += "=" * (4 - len(payload) % 4)
                try:
                    decoded = base64.b64decode(payload)
                    token_data = json.loads(decoded)
                    return token_data.get("email")
                except (ValueError, json.JSONDecodeError):
                    pass
    except (KeyError, TypeError, AttributeError):
        pass
    return None


# 兼容性别名
class OpenAIUsageChecker(CodexUsageChecker):
    """兼容性别名"""
    
    def __init__(self, access_token: str = None, usage_cache_dir=None):
        super().__init__(usage_cache_dir)
        self.access_token = access_token
    
    def get_account_summary(self, email: str = None) -> Dict:
        """获取账号使用情况摘要（兼容性方法）"""
        summary = self.get_usage_summary(email)
        return {
            "email": email or "Codex CLI",
            "check_time": summary["check_time"],
            "status": summary["status"],
            "usage_data": summary.get("token_usage", {}),
            "rate_limits": summary.get("rate_limits", {}),
            "errors": summary.get("errors", [])
        }


def extract_access_token_from_auth(auth_data: Dict) -> Optional[str]:
    """兼容性函数"""
    try:
        return auth_data.get("tokens", {}).get("access_token")
    except (KeyError, TypeError):
        return None


if __name__ == "__main__":
    checker = CodexUsageChecker()
    summary = checker.get_usage_summary()
    print(checker.format_usage_summary(summary))