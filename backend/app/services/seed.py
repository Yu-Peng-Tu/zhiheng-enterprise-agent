import hashlib
from copy import deepcopy
from pathlib import Path
from sqlalchemy.orm import Session
from ..models import Approval, Order, Document
from ..core.database import Base, engine, run_compat_migrations
from .documents import create_document, process_document

DATA = Path(__file__).resolve().parents[1] / "data"
ORDERS = [
    ("SQ100001","林晓","Aurora X1 无线耳机","delivered",899.0,"2026-10-20","2026-10-23","顺丰速运 · 已签收"),
    ("SQ100002","周远","Nimbus 机械键盘","shipped",529.0,"2026-11-01",None,"京东物流 · 运输中"),
    ("SQ100003","陈可","Lumen 便携显示器","processing",1499.0,"2026-11-03",None,"等待仓库出库"),
    ("SQ100004","赵宁","Aurora X1 无线耳机","delivered",899.0,"2026-09-12","2026-09-15","顺丰速运 · 已签收"),
    ("SQ100005","吴桐","Contour 人体工学椅","delivered",1899.0,"2026-10-28","2026-11-02","德邦物流 · 已签收"),
    ("SQ100006","孙一","Vista 4K 摄像头","cancelled",699.0,"2026-10-30",None,"订单已取消"),
]

def seed_database(db: Session):
    Base.metadata.create_all(bind=engine)
    run_compat_migrations()
    for values in ORDERS:
        if not db.get(Order, values[0]):
            db.add(Order(id=values[0],customer_name=values[1],product=values[2],status=values[3],amount=values[4],ordered_at=values[5],delivered_at=values[6],logistics=values[7]))
    # Legacy rows cannot recover a lost pre-modification value; preserve their best known draft.
    for approval in db.query(Approval).all():
        if approval.original_draft is None:
            approval.original_draft = deepcopy(approval.draft)
        if approval.actor is None and approval.status in {"approved", "rejected"}:
            approval.actor = "演示管理员"
    db.commit()
    for path in sorted((DATA / "policies").glob("*.md")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not db.query(Document).filter(Document.content_hash == digest).first():
            document, _ = create_document(db, path.name, ".md", path, digest)
            process_document(document.id, db)
