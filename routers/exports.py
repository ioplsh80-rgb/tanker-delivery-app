import io
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import models
from database import get_db
from routers.auth import get_current_user
from routers.deliveries import _apply_visibility_filter

router = APIRouter()

STATUS_LABELS = {
    "wait":     "대기중",
    "loaded":   "상차완료",
    "driving":  "운행중",
    "unloaded": "하차완료",
    "done":     "완료",
    "cancel":   "취소",
}


# ── 엑셀 내보내기 ──────────────────────────────────────────────────────────────
@router.get("/excel")
def export_excel(
    status: Optional[str] = None,
    driver_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = _apply_visibility_filter(db.query(models.Delivery), db, current_user)
    if status:
        query = query.filter(models.Delivery.status == status)
    if driver_id:
        query = query.filter(models.Delivery.driver_id == driver_id)
    if date_from:
        query = query.filter(models.Delivery.scheduled_date >= date_from)
    if date_to:
        query = query.filter(models.Delivery.scheduled_date <= date_to)
    deliveries = query.order_by(
        models.Delivery.scheduled_date, models.Delivery.delivery_time
    ).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "배송 목록"

    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_wrap = Alignment(horizontal="left", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    # 제목 (16열 전체 병합)
    ws.merge_cells("A1:P1")
    ws["A1"] = "탱크로리 배송 내역"
    ws["A1"].font = Font(bold=True, size=15, color="1E3A5F")
    ws["A1"].alignment = center
    ws.row_dimensions[1].height = 34

    ws.merge_cells("A2:P2")
    ws["A2"] = f"출력일: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}"
    ws["A2"].font = Font(size=10, color="6B7280")
    ws["A2"].alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[2].height = 18

    # 헤더 (16열)
    headers = [
        "번호", "유형", "업체명", "목적지", "품목", "수량(Kg)",
        "기사명", "차량번호", "배송날짜", "배송시간",
        "상차완료", "운행시작", "하차완료", "완료시간", "상태", "특이사항",
    ]
    col_widths = [6, 8, 16, 22, 20, 10, 10, 13, 13, 10, 10, 10, 10, 10, 10, 26]

    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF", size=11)

    for col_idx, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=3, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = thin_border
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = w
    ws.row_dimensions[3].height = 22

    status_fills = {
        "wait":     PatternFill("solid", fgColor="FEF3C7"),
        "loaded":   PatternFill("solid", fgColor="EDE9FE"),
        "driving":  PatternFill("solid", fgColor="DBEAFE"),
        "unloaded": PatternFill("solid", fgColor="CCFBF1"),
        "done":     PatternFill("solid", fgColor="DCFCE7"),
        "cancel":   PatternFill("solid", fgColor="FEE2E2"),
    }

    for row_idx, d in enumerate(deliveries, 4):
        row_values = [
            row_idx - 3,
            d.delivery_type or "출하",
            d.company,
            d.destination,
            d.item_name,
            d.quantity,
            d.driver_user.name if d.driver_user else "",
            d.vehicle_number or "",
            d.scheduled_date,
            d.delivery_time,
            d.loading_complete_time or "-",
            d.driving_time or "-",
            d.unloaded_time or "-",
            d.complete_time or "-",
            STATUS_LABELS.get(d.status, d.status),
            d.notes or "",
        ]
        status_fill = status_fills.get(d.status)
        for col_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            # 16열(특이사항)만 왼쪽 정렬, 15열(상태)에 상태 색상
            cell.alignment = left_wrap if col_idx == 16 else center
            cell.border = thin_border
            if col_idx == 15 and status_fill:
                cell.fill = status_fill
        ws.row_dimensions[row_idx].height = 18

    ws.freeze_panes = "A4"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"배송목록_{datetime.now().strftime('%Y%m%d')}.xlsx"
    encoded = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )
