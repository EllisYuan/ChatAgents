"""
会话管理模块

负责会话数据的持久化、加载和管理，使用 JSON 文件存储。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from filelock import FileLock

logger = logging.getLogger(__name__)

# 数据存储目录
DATA_DIR = Path(__file__).parent.parent / "data" / "sessions"
INDEX_FILE = DATA_DIR / "index.json"
LOCK_FILE = DATA_DIR / ".lock"

# 确保目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


class SessionManager:
    """会话管理器"""

    def __init__(self):
        """初始化会话管理器"""
        self.lock = FileLock(str(LOCK_FILE), timeout=10)

    def _ensure_index_exists(self) -> None:
        """确保索引文件存在"""
        if not INDEX_FILE.exists():
            with self.lock:
                # 双重检查，防止并发创建
                if not INDEX_FILE.exists():
                    self._write_json(INDEX_FILE, {"sessions": []})

    def _read_json(self, file_path: Path) -> dict:
        """安全读取 JSON 文件"""
        try:
            if file_path.exists():
                with open(file_path, encoding="utf-8") as f:
                    return cast(dict[str, Any], json.load(f))
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误: {file_path}, {e}")
            return {}
        except Exception as e:
            logger.error(f"读取文件失败: {file_path}, {e}")
            return {}

    def _write_json(self, file_path: Path, data: dict[str, Any]) -> None:
        """安全写入 JSON 文件（带备份）"""
        backup_path = file_path.with_suffix(".json.bak")

        try:
            # 如果原文件存在，先备份
            if file_path.exists():
                import shutil

                shutil.copy(file_path, backup_path)

            # 写入新数据
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 成功后删除备份
            if backup_path.exists():
                backup_path.unlink()

        except Exception as e:
            logger.error(f"写入文件失败: {file_path}, {e}")
            # 如果写入失败且有备份，尝试恢复
            if backup_path.exists() and not file_path.exists():
                import shutil

                shutil.copy(backup_path, file_path)
            raise

    def get_sessions_list(self) -> list[dict[str, Any]]:
        """
        获取会话列表（仅元数据）

        Returns:
            会话列表，按更新时间倒序排列
        """
        self._ensure_index_exists()

        with self.lock:
            data = self._read_json(INDEX_FILE)
            sessions = cast(list[dict[str, Any]], data.get("sessions", []))

            # 按更新时间倒序排列
            sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return sessions

    def get_session(self, session_id: str) -> dict | None:
        """
        获取会话详情

        Args:
            session_id: 会话ID

        Returns:
            会话数据，包含完整消息列表；如果不存在返回 None
        """
        session_file = DATA_DIR / f"{session_id}.json"

        if not session_file.exists():
            logger.warning(f"会话不存在: {session_id}")
            return None

        with self.lock:
            return self._read_json(session_file)

    def create_session(self, session_id: str, title: str | None = None) -> dict:
        """
        创建新会话

        Args:
            session_id: 会话ID
            title: 会话标题（可选，默认为 session_id）

        Returns:
            新创建的会话数据
        """
        self._ensure_index_exists()

        now = datetime.now().isoformat()
        session_data = {
            "session_id": session_id,
            "title": title or session_id,  # 默认使用 session_id 作为标题
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

        with self.lock:
            # 写入会话文件
            session_file = DATA_DIR / f"{session_id}.json"
            self._write_json(session_file, session_data)

            # 更新索引
            index_data = self._read_json(INDEX_FILE)
            index_data["sessions"].append(
                {
                    "session_id": session_id,
                    "title": session_data["title"],
                    "created_at": session_data["created_at"],
                    "updated_at": session_data["updated_at"],
                    "message_count": 0,
                }
            )
            self._write_json(INDEX_FILE, index_data)

        logger.info(f"创建会话: {session_id}, 标题: {title}")
        return session_data

    def save_session(self, session_data: dict[str, Any]) -> None:
        """
        保存会话数据

        Args:
            session_data: 会话数据，必须包含 session_id, title, messages
        """
        session_id = session_data.get("session_id")
        if not session_id:
            raise ValueError("session_data 必须包含 session_id")

        self._ensure_index_exists()

        now = datetime.now().isoformat()
        session_data["updated_at"] = now

        with self.lock:
            # 写入会话文件
            session_file = DATA_DIR / f"{session_id}.json"
            self._write_json(session_file, session_data)

            # 更新索引
            index_data = self._read_json(INDEX_FILE)
            sessions = index_data.get("sessions", [])

            # 查找并更新索引中的会话信息
            found = False
            for session in sessions:
                if session["session_id"] == session_id:
                    session["title"] = session_data.get("title", "新对话")
                    session["updated_at"] = now
                    session["message_count"] = len(session_data.get("messages", []))
                    found = True
                    break

            # 如果索引中不存在，添加新条目
            if not found:
                sessions.append(
                    {
                        "session_id": session_id,
                        "title": session_data.get("title", "新对话"),
                        "created_at": session_data.get("created_at", now),
                        "updated_at": now,
                        "message_count": len(session_data.get("messages", [])),
                    }
                )

            index_data["sessions"] = sessions
            self._write_json(INDEX_FILE, index_data)

        logger.info(f"保存会话: {session_id}")

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话ID

        Returns:
            是否删除成功
        """
        self._ensure_index_exists()
        session_file = DATA_DIR / f"{session_id}.json"

        with self.lock:
            # 删除会话文件
            if session_file.exists():
                session_file.unlink()

            # 从索引中移除
            index_data = self._read_json(INDEX_FILE)
            sessions = index_data.get("sessions", [])
            index_data["sessions"] = [s for s in sessions if s["session_id"] != session_id]
            self._write_json(INDEX_FILE, index_data)

        logger.info(f"删除会话: {session_id}")
        return True

    def rename_session(self, session_id: str, new_title: str) -> bool:
        """
        重命名会话

        Args:
            session_id: 会话ID
            new_title: 新标题

        Returns:
            是否重命名成功
        """
        self._ensure_index_exists()
        session_file = DATA_DIR / f"{session_id}.json"

        if not session_file.exists():
            logger.warning(f"会话不存在: {session_id}")
            return False

        with self.lock:
            # 更新会话文件
            session_data = self._read_json(session_file)
            session_data["title"] = new_title
            session_data["updated_at"] = datetime.now().isoformat()
            self._write_json(session_file, session_data)

            # 更新索引
            index_data = self._read_json(INDEX_FILE)
            sessions = index_data.get("sessions", [])
            for session in sessions:
                if session["session_id"] == session_id:
                    session["title"] = new_title
                    session["updated_at"] = session_data["updated_at"]
                    break
            self._write_json(INDEX_FILE, index_data)

        logger.info(f"重命名会话: {session_id} -> {new_title}")
        return True

    def auto_generate_title(self, first_message: str, max_length: int = 30) -> str:
        """
        从第一条消息自动生成会话标题

        Args:
            first_message: 第一条用户消息
            max_length: 标题最大长度

        Returns:
            生成的标题
        """
        # 去除空白字符
        title = first_message.strip()

        # 替换换行符为空格
        title = title.replace("\n", " ").replace("\r", " ")

        # 截断到最大长度
        if len(title) > max_length:
            title = title[:max_length] + "..."

        return title or "新对话"


# 全局单例
_session_manager = None


def get_session_manager() -> SessionManager:
    """获取会话管理器单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
