import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from app.models.canvas import CanvasDocument, CanvasTreeNode
from app.schemas.canvas import CanvasNodeResponse, CanvasResponse


def map_canvas_record(record: CanvasDocument) -> CanvasResponse:
    return CanvasResponse(
        id=record.id,
        nodeId=record.node_id,
        exists=True,
        name=record.name,
        xmlContent=record.xml_content,
        nodeInfo=json.loads(record.node_info_json),
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def map_tree_node_record(record: CanvasTreeNode) -> CanvasNodeResponse:
    return CanvasNodeResponse(
        id=record.id,
        parentId=record.parent_id,
        name=record.name,
        sortOrder=record.sort_order,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


class CanvasService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_tree_node(self, *, user_id: str, node_id: str) -> CanvasTreeNode | None:
        return self.db.scalar(
            select(CanvasTreeNode).where(
                CanvasTreeNode.id == node_id,
                CanvasTreeNode.user_id == user_id,
            )
        )

    def _resolve_next_sort_order(self, *, user_id: str, parent_id: str | None) -> int:
        siblings = self.db.scalars(
            select(CanvasTreeNode).where(
                CanvasTreeNode.user_id == user_id,
                CanvasTreeNode.parent_id == parent_id,
            )
        ).all()
        if not siblings:
            return 0
        return max(node.sort_order for node in siblings) + 1

    def _ensure_default_root_node(self, *, user_id: str) -> CanvasTreeNode:
        root_node = self.db.scalar(
            select(CanvasTreeNode)
            .where(
                CanvasTreeNode.user_id == user_id,
                CanvasTreeNode.parent_id.is_(None),
            )
            .order_by(asc(CanvasTreeNode.sort_order), asc(CanvasTreeNode.created_at))
        )
        if root_node is not None:
            return root_node

        existing_canvas = self.db.scalar(
            select(CanvasDocument)
            .where(CanvasDocument.user_id == user_id)
            .order_by(desc(CanvasDocument.updated_at), desc(CanvasDocument.created_at))
        )
        root_node_kwargs = {
            "user_id": user_id,
            "parent_id": None,
            "name": "默认节点",
            "sort_order": 0,
        }
        if existing_canvas is not None:
            root_node_kwargs["id"] = existing_canvas.node_id

        root_node = CanvasTreeNode(**root_node_kwargs)
        self.db.add(root_node)
        self.db.commit()
        self.db.refresh(root_node)
        return root_node

    def list_tree_nodes(self, user_id: str) -> list[CanvasNodeResponse]:
        self._ensure_default_root_node(user_id=user_id)
        records = self.db.scalars(
            select(CanvasTreeNode)
            .where(CanvasTreeNode.user_id == user_id)
            .order_by(
                asc(CanvasTreeNode.parent_id),
                asc(CanvasTreeNode.sort_order),
                asc(CanvasTreeNode.created_at),
            )
        ).all()
        return [map_tree_node_record(record) for record in records]

    def create_node(
        self,
        *,
        user_id: str,
        name: str,
        parent_id: str | None = None,
    ) -> CanvasNodeResponse:
        if parent_id is not None and self._get_tree_node(user_id=user_id, node_id=parent_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在。")

        record = CanvasTreeNode(
            user_id=user_id,
            parent_id=parent_id,
            name=name,
            sort_order=self._resolve_next_sort_order(user_id=user_id, parent_id=parent_id),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return map_tree_node_record(record)

    def save_canvas(
        self,
        user_id: str,
        node_id: str,
        name: str,
        xml_content: str,
        node_info: dict[str, Any],
    ) -> CanvasResponse:
        if self._get_tree_node(user_id=user_id, node_id=node_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在。")

        record = self.db.scalar(
            select(CanvasDocument).where(
                CanvasDocument.user_id == user_id,
                CanvasDocument.node_id == node_id,
            )
        )

        if record is None:
            record = CanvasDocument(
                user_id=user_id,
                node_id=node_id,
                name=name,
                xml_content=xml_content,
                node_info_json=json.dumps(node_info, ensure_ascii=False),
            )
            self.db.add(record)
        else:
            record.name = name
            record.xml_content = xml_content
            record.node_info_json = json.dumps(node_info, ensure_ascii=False)

        self.db.commit()
        self.db.refresh(record)
        return map_canvas_record(record)

    def get_canvas(self, user_id: str, node_id: str) -> CanvasResponse:
        if self._get_tree_node(user_id=user_id, node_id=node_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在。")

        record: CanvasDocument | None = self.db.scalar(
            select(CanvasDocument).where(
                CanvasDocument.user_id == user_id,
                CanvasDocument.node_id == node_id,
            )
        )
        if record is None:
            now = datetime.now()
            return CanvasResponse(
                id="",
                nodeId=node_id,
                exists=False,
                name="",
                xmlContent="",
                nodeInfo={},
                createdAt=now,
                updatedAt=now,
            )

        return map_canvas_record(record)
