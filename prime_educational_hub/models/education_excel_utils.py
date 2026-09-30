# -*- coding: utf-8 -*-
"""Shared Excel (.xlsx) export engine, using xlsxwriter — the natural
companion to the ReportLab PDF engine for reports users want to filter/sort
themselves (Collection Report, Outstanding Fees Report, ...)."""
import io

from odoo import models

import xlsxwriter


class EducationExcelUtils(models.AbstractModel):
    _name = 'education.excel.utils'
    _description = 'Shared Excel Export Engine'

    def build_simple_excel(self, title, meta_pairs, table_header, table_rows, totals=None, sheet_name='Report'):
        """
        title: sheet title, written as a merged header row.
        meta_pairs: list of (label, value) written as a compact info block.
        table_header / table_rows: the main data table.
        totals: optional list of (label, value) written after the table.
        Returns: xlsx bytes.
        """
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})
        sheet_name = (sheet_name or 'Report')[:31]  # Excel sheet name hard limit
        sheet = workbook.add_worksheet(sheet_name)

        title_format = workbook.add_format({'bold': True, 'font_size': 16, 'font_color': '#2c3e50'})
        meta_label_format = workbook.add_format({'bold': True, 'font_color': '#555555'})
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#2c3e50', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        cell_format = workbook.add_format({'border': 1})
        total_label_format = workbook.add_format({'bold': True, 'top': 2})
        total_value_format = workbook.add_format({'bold': True, 'top': 2})

        row = 0
        n_cols = max(len(table_header), 2) if table_header else 2
        sheet.merge_range(row, 0, row, n_cols - 1, title, title_format)
        row += 2

        for label, value in (meta_pairs or []):
            sheet.write(row, 0, label, meta_label_format)
            sheet.write(row, 1, value)
            row += 1
        if meta_pairs:
            row += 1

        if table_header:
            for col, head in enumerate(table_header):
                sheet.write(row, col, head, header_format)
            header_row = row
            row += 1
            for data_row in (table_rows or []):
                for col, value in enumerate(data_row):
                    sheet.write(row, col, value, cell_format)
                row += 1
            sheet.autofilter(header_row, 0, max(row - 1, header_row), n_cols - 1)
            for col in range(n_cols):
                sheet.set_column(col, col, 20)

        if totals:
            row += 1
            for label, value in totals:
                sheet.write(row, 0, label, total_label_format)
                sheet.write(row, 1, value, total_value_format)
                row += 1

        workbook.close()
        xlsx_bytes = buffer.getvalue()
        buffer.close()
        return xlsx_bytes
