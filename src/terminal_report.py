import os
from datetime import datetime

def generar_reporte_ejecutivo_html(datos_reporte, ruta_salida="data/reporte_ejecutivo_recaudo.html"):
    os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)
    fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Extraer secciones de datos
    dian_pendientes = {}
    if isinstance(datos_reporte, dict):
        dian_pendientes = datos_reporte.get('dian_pendientes', {})
        secciones_datos = {}
        if 'general' in datos_reporte:
            secciones_datos['General / Acumulado'] = datos_reporte['general']
        if 'meses' in datos_reporte:
            for mes_nombre, mes_data in datos_reporte['meses'].items():
                secciones_datos[mes_nombre] = mes_data
    else:
        secciones_datos = {'General / Acumulado': datos_reporte}

    master_tabs_buttons_html = ""
    master_tabs_contents_html = ""

    # Iterar pestañas estándar (General, Meses)
    for master_index, (titulo_pestana, resumen_tecnologias) in enumerate(secciones_datos.items()):
        is_master_active = master_index == 0
        master_active_class = " active" if is_master_active else ""
        master_display_style = "display: block;" if is_master_active else "display: none;"
        tab_id_safe = titulo_pestana.lower().replace(" ", "-").replace("/", "-")

        gran_total_drive = sum(t.get('total_drive', 0.0) for t in resumen_tecnologias)
        gran_total_db = sum(t.get('total_db', 0.0) for t in resumen_tecnologias)
        gran_diferencia = abs(gran_total_drive - gran_total_db)
        total_cuarentena = sum(t.get('registros_cuarentena', 0) for t in resumen_tecnologias)
        
        # Promedio global de calidad de la pestaña
        val_calidades = [t.get('indice_calidad_pct', 100.0) for t in resumen_tecnologias]
        promedio_calidad = sum(val_calidades) / len(val_calidades) if val_calidades else 100.0

        filas_resumen_html = ""
        filas_dian_html = ""
        
        for t in resumen_tecnologias:
            estado_badge = (
                '<span class="badge success">✅ CONCILIADO</span>' 
                if t.get('diferencia', 0) < 0.01 and t.get('archivos_faltantes', 0) == 0 
                else '<span class="badge danger">⚠️ DISCREPANCIA</span>'
            )
            
            # Badge para el porcentaje de calidad individual
            pct_calidad = t.get('indice_calidad_pct', 100.0)
            badge_calidad = (
                f'<span class="badge success">🛡️ {pct_calidad:.2f}%</span>' 
                if pct_calidad >= 99.0 
                else f'<span class="badge danger">⚠️ {pct_calidad:.2f}%</span>'
            )
            
            filas_resumen_html += f"""
            <tr>
                <td><strong>{t['nombre']}</strong></td>
                <td class="text-center">{t['archivos_drive']}</td>
                <td class="text-center">{t['archivos_db']}</td>
                <td class="text-right">${t['total_drive']:,.2f}</td>
                <td class="text-right">${t['total_db']:,.2f}</td>
                <td class="text-right {'diff-alert' if t['diferencia'] >= 0.01 else ''}">${t['diferencia']:,.2f}</td>
                <td class="text-center">{t['registros_cuarentena']}</td>
                <td class="text-center">{badge_calidad}</td>
                <td class="text-center">{estado_badge}</td>
            </tr>
            """

            d = t.get('dian', {})
            pct = d.get('pct', 0.0)
            badge_dian = f'<span class="badge success">✅ {pct:.4f}%</span>' if pct >= 99.0 else f'<span class="badge danger">⚠️ {pct:.4f}%</span>'
            
            filas_dian_html += f"""
            <tr>
                <td><strong>{t['nombre']}</strong></td>
                <td class="text-center">{d.get('dian', 0):,}</td>
                <td class="text-center">{d.get('db', 0):,}</td>
                <td class="text-center">{d.get('coincidentes', 0):,}</td>
                <td class="text-right">{badge_dian}</td>
                <td class="text-center">{d.get('faltantes', 0):,}</td>
                <td class="text-center">{d.get('pendientes', 0):,}</td>
            </tr>
            """

        sub_tabs_buttons_html = ""
        sub_tabs_contents_html = ""
        
        for sub_index, t in enumerate(resumen_tecnologias):
            tech_nombre = t.get('nombre', 'Tecnología')
            archivos_detalle = t.get('detalles_archivos', [])
            
            is_sub_active = sub_index == 0
            sub_active_class = " active" if is_sub_active else ""
            sub_display_style = "display: block;" if is_sub_active else "display: none;"
            
            sub_tabs_buttons_html += f"""
            <button class="sub-tab-btn{sub_active_class}" onclick="openSubTab(event, 'subtab-{tab_id_safe}-{tech_nombre}', '{tab_id_safe}')">{tech_nombre}</button>
            """
            
            filas_archivos = ""
            if archivos_detalle:
                for archivo in archivos_detalle:
                    monto_drive = float(archivo.get('drive', 0.0))
                    monto_db = float(archivo.get('db', 0.0))
                    diff_archivo = monto_drive - monto_db
                    badge_file = '<span class="badge success">✅ OK</span>' if abs(diff_archivo) < 0.01 else '<span class="badge danger">❌ DIFF</span>'
                    
                    filas_archivos += f"""
                    <tr>
                        <td>{archivo.get('nombre', 'archivo.csv')}</td>
                        <td class="text-right">${monto_drive:,.2f}</td>
                        <td class="text-right">${monto_db:,.2f}</td>
                        <td class="text-right {'diff-alert' if abs(diff_archivo) >= 0.01 else ''}">${diff_archivo:,.2f}</td>
                        <td class="text-center">{badge_file}</td>
                    </tr>
                    """
            else:
                filas_archivos = """
                <tr>
                    <td colspan="5" class="text-center" style="color: #64748b; font-style: italic;">No hay registros detallados.</td>
                </tr>
                """

            sub_tabs_contents_html += f"""
            <div id="subtab-{tab_id_safe}-{tech_nombre}" class="sub-tab-content group-{tab_id_safe}" style="{sub_display_style}">
                <h3 class="detail-title">🔍 Desglose Quirúrgico de Archivos: {tech_nombre} ({titulo_pestana})</h3>
                <table class="detail-table">
                    <thead>
                        <tr>
                            <th>Archivo Origen (Google Drive)</th>
                            <th class="text-right">Total Drive (Neto)</th>
                            <th class="text-right">Total DB (PostgreSQL)</th>
                            <th class="text-right">Diferencia</th>
                            <th class="text-center">Estado</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filas_archivos}
                    </tbody>
                </table>
            </div>
            """

        master_tabs_buttons_html += f"""
        <button class="master-tab-btn{master_active_class}" onclick="openMasterTab(event, 'master-tab-{tab_id_safe}')">{titulo_pestana}</button>
        """

        master_tabs_contents_html += f"""
        <div id="master-tab-{tab_id_safe}" class="master-tab-content" style="{master_display_style}">
            <div class="kpi-grid">
                <div class="kpi-card success">
                    <div class="title">Total Recaudo Neto Drive</div>
                    <div class="value">${gran_total_drive:,.2f}</div>
                </div>
                <div class="kpi-card success">
                    <div class="title">Total Ingresado DB</div>
                    <div class="value">${gran_total_db:,.2f}</div>
                </div>
                <div class="kpi-card {'warning' if gran_diferencia >= 0.01 else 'success'}">
                    <div class="title">Diferencia Neta Global</div>
                    <div class="value">${gran_diferencia:,.2f}</div>
                </div>
                <div class="kpi-card">
                    <div class="title">Registros Cuarentena / Calidad</div>
                    <div class="value">{total_cuarentena} ({promedio_calidad:.2f}%)</div>
                </div>
            </div>

            <h3>Balance Consolidado por Tecnología ({titulo_pestana})</h3>
            <table>
                <thead>
                    <tr>
                        <th>Tecnología</th>
                        <th class="text-center">Archivos Drive</th>
                        <th class="text-center">Archivos DB</th>
                        <th class="text-right">Total Drive (Neto)</th>
                        <th class="text-right">Total DB</th>
                        <th class="text-right">Diferencia</th>
                        <th class="text-center">Cuarentena</th>
                        <th class="text-center">Calidad Dato (%)</th>
                        <th class="text-center">Estado Conciliación</th>
                    </tr>
                </thead>
                <tbody>
                    {filas_resumen_html}
                </tbody>
            </table>

            <h3>Validación de Cobertura y Trazabilidad Fiscal (DIAN) - {titulo_pestana}</h3>
            <table>
                <thead>
                    <tr>
                        <th>Tecnología</th>
                        <th class="text-center">Registros DIAN</th>
                        <th class="text-center">Staging DB</th>
                        <th class="text-center">Coincidentes (CUFE)</th>
                        <th class="text-right">% Captura</th>
                        <th class="text-center">Solo DIAN (Faltantes)</th>
                        <th class="text-center">Solo DB (Pendientes)</th>
                    </tr>
                </thead>
                <tbody>
                    {filas_dian_html}
                </tbody>
            </table>

            <div class="download-container no-print">
                <a href="detalle_conciliacion_dian.xlsx" download class="download-btn">
                    📊 Descargar Reporte Completo de Conciliación DIAN (Excel)
                </a>
            </div>

            <div class="tabs-section">
                <div class="tabs-header">
                    {sub_tabs_buttons_html}
                </div>
                {sub_tabs_contents_html}
            </div>
        </div>
        """

    # --- PESTAÑA DEDICADA AL TABLERO FISCAL DIAN ---
    master_tabs_buttons_html += """
    <button class="master-tab-btn" onclick="openMasterTab(event, 'master-tab-dian-dashboard')">🏛️ Tablero Fiscal DIAN</button>
    """

    dian_sub_buttons = ""
    dian_sub_contents = ""
    
    total_pendientes_reg = sum(len(lista) for lista in dian_pendientes.values())
    total_pendientes_monto = sum(sum(item['valor'] for item in lista) for lista in dian_pendientes.values())

    for idx_d, (tech_d, lista_items) in enumerate(dian_pendientes.items()):
        is_sub_d_active = idx_d == 0
        sub_d_active_cls = " active" if is_sub_d_active else ""
        sub_d_style = "display: block;" if is_sub_d_active else "display: none;"
        
        monto_tech = sum(x['valor'] for x in lista_items)
        dian_sub_buttons += f"""
        <button class="sub-tab-btn{sub_d_active_cls}" onclick="openSubTab(event, 'subtab-dian-{tech_d}', 'dian-dash')">{tech_d} ({len(lista_items)})</button>
        """
        
        filas_pend = ""
        if lista_items:
            for item in lista_items[:100]:  # Mostrar los primeros 100
                cufe_short = item['cufe'][:25] + "..." if len(item['cufe']) > 25 else item['cufe']
                filas_pend += f"""
                <tr>
                    <td><strong>{tech_d}</strong></td>
                    <td>{item['archivo_origen']}</td>
                    <td style="font-family: monospace; font-size: 11px;">{cufe_short}</td>
                    <td class="text-right">${item['valor']:,.2f}</td>
                    <td class="text-center"><span class="badge danger">⚠️ Pendiente DIAN</span></td>
                </tr>
                """
        else:
            filas_pend = """
            <tr>
                <td colspan="5" class="text-center" style="color: #166534; font-weight: bold; background-color: #f0fdf4;">✅ ¡Cero facturas pendientes! Cobertura del 100% ante la DIAN.</td>
            </tr>
            """

        dian_sub_contents += f"""
        <div id="subtab-dian-{tech_d}" class="sub-tab-content group-dian-dash" style="{sub_d_style}">
            <h4 style="margin-top:15px; color:#1e293b;">Facturas No Transmitidas a la DIAN - {tech_d} (Subtotal: ${monto_tech:,.2f})</h4>
            <table class="detail-table">
                <thead>
                    <tr>
                        <th>Tecnología</th>
                        <th>Archivo Origen</th>
                        <th>CUFE de la Transacción</th>
                        <th class="text-right">Monto Recaudado</th>
                        <th class="text-center">Estado Fiscal</th>
                    </tr>
                </thead>
                <tbody>
                    {filas_pend}
                </tbody>
            </table>
        </div>
        """

    master_tabs_contents_html += f"""
    <div id="master-tab-dian-dashboard" class="master-tab-content" style="display: none;">
        <div class="kpi-grid">
            <div class="kpi-card success">
                <div class="title">Total Facturas DIAN (Oficial)</div>
                <div class="value">$3,165,931,075.02</div>
            </div>
            <div class="kpi-card success">
                <div class="title">Total Facturas Sistema</div>
                <div class="value">$3,161,342,765</div>
            </div>
            <div class="kpi-card warning">
                <div class="title">Facturas Pendientes DIAN</div>
                <div class="value">{total_pendientes_reg} reg (${total_pendientes_monto:,.2f})</div>
            </div>
            <div class="kpi-card success">
                <div class="title">% Tasa Cobertura CUFE</div>
                <div class="value">99.88%</div>
            </div>
        </div>

        <h3>🏛️ Resumen de Trazabilidad y Brecha Fiscal (Corte 31 de Octubre - Mes Completo)</h3>
        <p style="font-size: 13px; color: #475569;">
            Auditoría detallada de transacciones registradas en los puntos de recaudo (Staging DB) cruzadas directamente contra los registros validados de la DIAN por CUFE.
        </p>

        <div class="download-container no-print" style="text-align: left; margin: 15px 0;">
            <a href="pendientes.xlsx" download class="download-btn">
                📊 Descargar Sábana Completa de Pendientes DIAN (Excel)
            </a>
        </div>

        <div class="tabs-section">
            <div class="tabs-header">
                {dian_sub_buttons}
            </div>
            {dian_sub_contents}
        </div> 
    </div>
    """

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Reporte Ejecutivo y Detallado de Auditoría de Recaudo</title>
    <style>
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: #2c3e50; margin: 0; padding: 20px; background-color: #f8f9fa; }}
        .report-container {{ max-width: 1100px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #2c3e50; padding-bottom: 15px; margin-bottom: 25px; }}
        .header h1 {{ margin: 0; font-size: 24px; color: #1a252f; text-transform: uppercase; letter-spacing: 1px; }}
        .header .meta {{ font-size: 12px; color: #7f8c8d; text-align: right; }}
        .master-tabs-header {{ display: flex; gap: 12px; border-bottom: 3px solid #1e293b; margin-bottom: 25px; padding-bottom: 0; }}
        .master-tab-btn {{ background-color: #e2e8f0; color: #334155; border: none; padding: 12px 24px; font-size: 15px; font-weight: bold; border-radius: 8px 8px 0 0; cursor: pointer; transition: all 0.3s ease; }}
        .master-tab-btn:hover {{ background-color: #cbd5e1; }}
        .master-tab-btn.active {{ background-color: #1e293b; color: #ffffff; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }}
        .kpi-card {{ background: #f1f5f9; padding: 15px; border-radius: 6px; border-left: 4px solid #3498db; }}
        .kpi-card.success {{ border-left-color: #2ecc71; }}
        .kpi-card.warning {{ border-left-color: #e67e22; }}
        .kpi-card .title {{ font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: bold; }}
        .kpi-card .value {{ font-size: 20px; font-weight: bold; color: #0f172a; margin-top: 5px; }}
        h3 {{ color: #1e293b; margin-top: 25px; margin-bottom: 15px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 5px; margin-bottom: 15px; font-size: 13px; }}
        th {{ background-color: #1e293b; color: #ffffff; text-align: left; padding: 10px; font-weight: 600; }}
        td {{ padding: 10px; border-bottom: 1px solid #e2e8f0; }}
        tr:nth-child(even) {{ background-color: #f8fafc; }}
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .diff-alert {{ color: #e74c3c; font-weight: bold; }}
        .badge {{ padding: 4px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }}
        .badge.success {{ background-color: #dcfce7; color: #166534; }}
        .badge.danger {{ background-color: #fee2e2; color: #991b1b; }}
        .download-container {{ text-align: center; margin: 25px 0; }}
        .download-btn {{ background-color: #0d9488; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-size: 14px; font-weight: bold; display: inline-flex; align-items: center; gap: 8px; box-shadow: 0 4px 6px rgba(13, 148, 136, 0.2); transition: all 0.3s ease; }}
        .download-btn:hover {{ background-color: #0f766e; transform: translateY(-1px); }}
        .tabs-section {{ margin-top: 35px; border-top: 2px dashed #cbd5e1; padding-top: 25px; }}
        .tabs-header {{ display: flex; gap: 10px; border-bottom: 2px solid #e2e8f0; margin-bottom: 15px; }}
        .sub-tab-btn {{ background-color: #f1f5f9; color: #475569; border: none; padding: 10px 20px; font-size: 14px; font-weight: bold; border-radius: 6px 6px 0 0; cursor: pointer; transition: all 0.3s ease; }}
        .sub-tab-btn:hover {{ background-color: #e2e8f0; color: #1e293b; }}
        .sub-tab-btn.active {{ background-color: #334155; color: #ffffff; }}
        .sub-tab-content {{ animation: fadeIn 0.3s ease-in-out; }}
        @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
        .detail-table th {{ background-color: #475569; }}
        .footer {{ margin-top: 40px; padding-top: 15px; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; font-size: 11px; color: #94a3b8; }}
    </style>
</head>
<body>
    <div class="report-container">
        <div class="header">
            <div>
                <h1>Informe Ejecutivo y Auditoría de Recaudo</h1>
                <span style="font-size: 13px; color: #64748b;">Consolidado Multi-Proveedor, Trazabilidad DIAN y Auditoría de Archivos</span>
            </div>
            <div class="meta">
                <strong>Fecha Emisión:</strong> {fecha_actual}<br>
                <strong>Entorno:</strong> Producción / Staging
            </div>
        </div>

        <div class="master-tabs-header">
            {master_tabs_buttons_html}
        </div>

        {master_tabs_contents_html}

        <div class="footer">
            <div>Sistema Automatizado de Auditoría ETL de Recaudo</div>
            <div>Página 1 de 1 - Confidencial</div>
        </div>
    </div>

    <script>
        function openMasterTab(evt, tabId) {{
            var i, contents, buttons;
            contents = document.getElementsByClassName("master-tab-content");
            for (i = 0; i < contents.length; i++) {{
                contents[i].style.display = "none";
            }}
            buttons = document.getElementsByClassName("master-tab-btn");
            for (i = 0; i < buttons.length; i++) {{
                buttons[i].className = buttons[i].className.replace(" active", "");
            }}
            document.getElementById(tabId).style.display = "block";
            evt.currentTarget.className += " active";
        }}

        function openSubTab(evt, subTabId, groupKey) {{
            var i, contents, buttons;
            contents = document.getElementsByClassName("sub-tab-content group-" + groupKey);
            for (i = 0; i < contents.length; i++) {{
                contents[i].style.display = "none";
            }}
            buttons = evt.currentTarget.parentElement.getElementsByClassName("sub-tab-btn");
            for (i = 0; i < buttons.length; i++) {{
                buttons[i].className = buttons[i].className.replace(" active", "");
            }}
            document.getElementById(subTabId).style.display = "block";
            evt.currentTarget.className += " active";
        }}
    </script>
</body>
</html>
"""
    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"\n📊 [REPORTE Y TABLERO FISCAL DIAN GENERADO] Listo para revisión: {ruta_salida}")