import streamlit as st
import pandas as pd
import plotly.express as px
from urllib.parse import quote_plus
import io
import os
import requests
from PIL import Image as PILImage
from datetime import datetime
from dateutil.relativedelta import relativedelta

# Libs para PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, Frame, PageTemplate
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

# --- CONFIGURAÇÕES GLOBAIS ---
SHEET_ID = st.secrets["SHEET_ID"]
ABA_NOME = "Pedidos Individuais"
NOME_EMPRESA = "Papello Embalagens"
LOGO_ARQUIVO_LOCAL = "logo.png"

# Paleta de Cores da Marca
BRAND_COLORS = {
    "primary": "#96CA00",
    "secondary": "#84A802",
    "highlight": "#C5DF56",
}
COR_TEXTO_PDF = '#333333'
# -----------------------------------------------------------------------------
# --- FUNÇÃO DE LOGIN ---
def check_password():
    """Retorna `True` se a senha estiver correta ou já autenticada."""

    # Verifica se o usuário já está autenticado na sessão.
    if st.session_state.get("authenticated", False):
        return True

    # Cria o formulário de login.
    with st.form("login_form"):
        st.image(LOGO_ARQUIVO_LOCAL, width=200)
        st.header("Acesso Restrito")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")

        # Verifica a senha quando o botão é pressionado.
        if submitted:
            # Compara a senha digitada com a senha armazenada no secrets.toml
            if password == st.secrets["PASSWORD"]:
                st.session_state["authenticated"] = True
                st.rerun()  # Recarrega a página para mostrar o dashboard
            else:
                st.error("Senha incorreta")
    return False

# --- FUNÇÕES AUXILIARES ---

def formatar_brl(valor):
    if pd.isna(valor): return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def aplicar_estilo_customizado():
    # Estilo simplificado para tema claro com cores da marca
    st.markdown(f"""
    <style>
        /* Fundo da sidebar */
        [data-testid="stSidebar"] {{
            background-color: #f0f2f6;
        }}
        /* Cor dos valores dos KPIs */
        .stMetricValue {{
            color: {BRAND_COLORS['secondary']};
        }}
        /* Títulos h1, h2, h3 */
        h1, h2, h3 {{
            color: {BRAND_COLORS['secondary']};
        }}
        /* Botão principal */
        .stButton>button {{
            background-color: {BRAND_COLORS['primary']};
            color: white;
        }}
        .stButton>button:hover {{
            background-color: {BRAND_COLORS['secondary']};
            color: white;
        }}
    </style>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=600)
def carregar_dados_planilha(sheet_id, sheet_name):
    sheet_name_encoded = quote_plus(sheet_name)
    url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name_encoded}'
    try:
        df = pd.read_csv(url)
        # --- LÓGICA DE FILTRAGEM ---
        status_incluir = ['Aprovado', 'Em Produção', 'Despachado', 'Concluído', 'Tracking']
        df = df[df['Status_do_Pedido'].isin(status_incluir)]
        df['Data'] = pd.to_datetime(df['Data_Pedido_Realizado'], format='%d/%m/%Y', errors='coerce')
        df['Valor'] = df['Valor_do_Pedido'].astype(str).str.replace('R$', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False).astype(float)
        df = df.dropna(subset=['Data', 'Valor'])
        
        # ADICIONADO: Filtro para garantir que a base de dados só contenha registros a partir de 2025
        df = df[df['Data'] >= '2025-01-01']
        
        # --- LIMPEZA E TRANSFORMAÇÃO ---
        mapa_recorrencia = {'Nuvem Novo': 'Cliente Novo', 'Nuvem Recorrente': 'Cliente Recorrente'}
        df['Tipo_Cliente'] = df['Status_recorrencia'].map(mapa_recorrencia).fillna('Não Definido')
        mapa_pagamento = {'credit_card': 'Cartão de Crédito', 'pix': 'Pix', 'boleto': 'Boleto', 'free': 'Personalizado', 'custon': 'Personalizado', 'custom': 'Personalizado', 'offline': 'Personalizado'}
        df['Forma_Pagamento_Limpa'] = df['forma_pagamento'].str.lower().str.strip()
        df['Forma_Pagamento'] = df['Forma_Pagamento_Limpa'].map(mapa_pagamento).fillna('Outros')
        df = df.rename(columns={'Estado': 'Estado', 'Cidade': 'Cidade'})
        return df[['Data', 'Valor', 'Tipo_Cliente', 'Forma_Pagamento', 'Estado', 'Cidade']]
    except Exception as e:
        st.error(f"Não foi possível carregar ou processar os dados da planilha. Erro: {e}")
        return pd.DataFrame()

# --- FUNÇÕES DE GERAÇÃO DE PDF ---
def setup_fonts():
    # ...
    font_regular_path, font_bold_path = 'Montserrat-Regular.ttf', 'Montserrat-Bold.ttf'
    if not os.path.exists(font_regular_path):
        try:
            r = requests.get("https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Regular.ttf")
            with open(font_regular_path, 'wb') as f: f.write(r.content)
        except Exception: return False
    if not os.path.exists(font_bold_path):
        try:
            r = requests.get("https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf")
            with open(font_bold_path, 'wb') as f: f.write(r.content)
        except Exception: return False
    try:
        pdfmetrics.registerFont(TTFont('Montserrat', font_regular_path))
        pdfmetrics.registerFont(TTFont('Montserrat-Bold', font_bold_path))
        pdfmetrics.registerFontFamily('Montserrat', normal='Montserrat', bold='Montserrat-Bold')
        return True
    except: return False
class PDFTemplate(SimpleDocTemplate):
    # ...
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logo_bytes = get_logo_bytes()
    def beforePage(self):
        c = self.canv; c.saveState()
        c.setFillColor(colors.HexColor(BRAND_COLORS['primary']))
        c.rect(0, letter[1] - 0.7*inch, letter[0], 0.7*inch, fill=1, stroke=0)
        if self.logo_bytes:
            logo = ImageReader(self.logo_bytes)
            c.drawImage(logo, 0.5*inch, letter[1] - 0.55*inch, width=1.5*inch, height=0.4*inch, preserveAspectRatio=True, mask='auto')
        c.setFont('Helvetica-Bold', 14); c.setFillColor(colors.white)
        c.drawRightString(letter[0] - 0.5*inch, letter[1] - 0.45*inch, "Relatório de Desempenho")
        c.restoreState()
    def afterPage(self):
        c = self.canv; c.saveState()
        c.setFont('Helvetica', 9); c.setFillColor(colors.grey)
        c.drawString(0.5*inch, 0.5*inch, f"{NOME_EMPRESA} - Gerado em {datetime.now().strftime('%d/%m/%Y')}")
        c.drawRightString(letter[0] - 0.5*inch, 0.5*inch, f"Página {self.page}")
        c.restoreState()
@st.cache_resource
def get_logo_bytes():
    # ...
    if os.path.exists(LOGO_ARQUIVO_LOCAL):
        try:
            with open(LOGO_ARQUIVO_LOCAL, "rb") as f:
                return io.BytesIO(f.read())
        except Exception as e:
            st.sidebar.error(f"Erro ao carregar o logo local: {e}")
            return None
    else:
        st.sidebar.warning(f"Arquivo '{LOGO_ARQUIVO_LOCAL}' não encontrado.")
        return None
def gerar_pdf_report(df, kpis, df_pagamentos, df_estados_fat, filtro_data):
    # ...
    font_ok = setup_fonts(); font_name = "Montserrat" if font_ok else "Helvetica"
    buffer = io.BytesIO()
    doc = PDFTemplate(buffer, pagesize=letter, topMargin=1*inch, bottomMargin=1*inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Titulo', parent=styles['h1'], fontName=f'{font_name}-Bold', fontSize=22, alignment=TA_CENTER, textColor=colors.HexColor(BRAND_COLORS['secondary'])))
    styles.add(ParagraphStyle(name='Subtitulo', parent=styles['h2'], fontName=f'{font_name}-Bold', textColor=COR_TEXTO_PDF, spaceBefore=20))
    styles.add(ParagraphStyle(name='Corpo', parent=styles['Normal'], fontName=font_name, textColor=COR_TEXTO_PDF))
    story = []
    story.append(Paragraph("Visão Geral do Período", styles['Titulo']))
    story.append(Paragraph(f"Período de Análise: {filtro_data[0].strftime('%d/%m/%Y')} a {filtro_data[1].strftime('%d/%m/%Y')}", styles['Corpo']))
    story.append(Spacer(1, 0.3*inch))
    kpi_data = [[Paragraph('<b>Faturamento Total</b>', styles['Corpo']), Paragraph(formatar_brl(kpis['faturamento_total']), styles['Corpo'])], [Paragraph('<b>Total de Pedidos</b>', styles['Corpo']), Paragraph(str(kpis['total_pedidos']), styles['Corpo'])], [Paragraph('<b>Ticket Médio</b>', styles['Corpo']), Paragraph(formatar_brl(kpis['ticket_medio']), styles['Corpo'])]]
    t_kpi = Table(kpi_data, colWidths=[2.5*inch, 4*inch])
    t_kpi.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('GRID', (0,0), (-1,-1), 1, colors.HexColor(BRAND_COLORS['highlight'])), ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F0F0F0'))]))
    story.append(t_kpi)
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Faturamento por Forma de Pagamento", styles['Subtitulo']))
    tabela_pag_data = [["Forma de Pagamento", "Faturamento", "% do Total"]] + df_pagamentos[['Forma_Pagamento', 'Faturamento_Formatado', 'Percentual_Formatado']].values.tolist()
    t_pag = Table(tabela_pag_data)
    t_pag.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor(BRAND_COLORS['secondary'])), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), f'{font_name}-Bold'), ('GRID', (0,0), (-1,-1), 1, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke)]))
    story.append(t_pag)
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Top 10 Estados por Faturamento", styles['Subtitulo']))
    tabela_est_fat_data = [["Estado", "Faturamento"]] + df_estados_fat[['Estado', 'Valor_Formatado']].values.tolist()
    t_est_fat = Table(tabela_est_fat_data)
    t_est_fat.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor(BRAND_COLORS['secondary'])), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), f'{font_name}-Bold'), ('GRID', (0,0), (-1,-1), 1, colors.grey), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke)]))
    story.append(t_est_fat)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

# --- CONSTRUÇÃO DO DASHBOARD ---
def main():

    st.set_page_config(page_title=f"Dashboard Planilha - {NOME_EMPRESA}", layout="wide", page_icon="📊")
    if check_password():
        aplicar_estilo_customizado()
        logo_bytes = get_logo_bytes()
        if logo_bytes:
            st.sidebar.image(logo_bytes, use_container_width=True)
        else:
            st.sidebar.markdown(f"### {NOME_EMPRESA}")
        st.sidebar.header("Filtros Interativos")
        st.title("DASHBOARD ANÁLISE FINANCEIRA")
        df_base = carregar_dados_planilha(SHEET_ID, ABA_NOME)
        if df_base.empty:
            st.warning("Nenhum dado válido para exibir. Verifique a planilha ou os filtros.")
            st.stop()
        data_max = df_base['Data'].max().date()
        data_min = df_base['Data'].min().date()
        data_inicio_filtro = data_max - relativedelta(months=6)
        if data_inicio_filtro < data_min: data_inicio_filtro = data_min
        filtro_data = st.sidebar.date_input("Selecione o Período", value=(data_inicio_filtro, data_max), min_value=data_min, max_value=data_max, format="DD/MM/YYYY")
        estados_disponiveis = sorted(df_base['Estado'].dropna().unique())
        filtro_estado = st.sidebar.multiselect("Selecione o Estado", options=estados_disponiveis, default=estados_disponiveis)
        if len(filtro_data) != 2:
            st.sidebar.warning("Por favor, selecione um período de início e fim.")
            st.stop()
        df_filtrado = df_base[(df_base['Data'].dt.date >= filtro_data[0]) & (df_base['Data'].dt.date <= filtro_data[1]) & (df_base['Estado'].isin(filtro_estado))]
        if df_filtrado.empty:
            st.warning("Nenhum dado encontrado para os filtros selecionados.")
            st.stop()
        faturamento_total = df_filtrado['Valor'].sum()
        total_pedidos = len(df_filtrado)
        ticket_medio = faturamento_total / total_pedidos if total_pedidos > 0 else 0
        kpis = {"faturamento_total": faturamento_total, "total_pedidos": total_pedidos, "ticket_medio": ticket_medio}
        st.markdown("### Visão Geral do Período Selecionado")
        col1, col2, col3 = st.columns(3)
        col1.metric("Faturamento Total", formatar_brl(faturamento_total))
        col2.metric("Total de Pedidos", f"{total_pedidos}")
        col3.metric("Ticket Médio", formatar_brl(ticket_medio))
        st.markdown("---")
        col_rec, col_pag = st.columns(2)
        with col_rec:
            st.subheader("Clientes Novos vs. Recorrentes")
            df_rec = df_filtrado['Tipo_Cliente'].value_counts().reset_index()
            fig_rec = px.pie(df_rec, names='Tipo_Cliente', values='count', title="Distribuição de Pedidos", color_discrete_sequence=[BRAND_COLORS['primary'], BRAND_COLORS['secondary'], BRAND_COLORS['highlight']])
            st.plotly_chart(fig_rec, use_container_width=True)
        with col_pag:
            st.subheader("Faturamento por Pagamento")
            df_pag = df_filtrado.groupby('Forma_Pagamento')['Valor'].sum().reset_index()
            fig_pag = px.pie(df_pag, names='Forma_Pagamento', values='Valor', title="Distribuição do Faturamento")
            st.plotly_chart(fig_pag, use_container_width=True)
        st.markdown("---")
        st.subheader("Análise Geográfica (Top 10)")
        col_est_fat, col_est_ped = st.columns(2)
        with col_est_fat:
            df_estados_fat = df_filtrado.groupby('Estado')['Valor'].sum().nlargest(10).reset_index()
            fig_est_fat = px.bar(df_estados_fat, x='Estado', y='Valor', title="Faturamento por Estado", text_auto='.2s', labels={'Valor': 'Faturamento (R$)'})
            fig_est_fat.update_traces(marker_color=BRAND_COLORS['primary'])
            st.plotly_chart(fig_est_fat, use_container_width=True)
        with col_est_ped:
            df_estados_pedidos = df_filtrado['Estado'].value_counts().nlargest(10).reset_index()
            fig_est_ped = px.bar(df_estados_pedidos, x='Estado', y='count', title="Nº de Pedidos por Estado", text_auto=True, labels={'count': 'Nº de Pedidos'})
            fig_est_ped.update_traces(marker_color=BRAND_COLORS['secondary'])
            st.plotly_chart(fig_est_ped, use_container_width=True)
        st.sidebar.header("Exportar Relatório")
        if st.sidebar.button("Gerar Relatório em PDF"):
            with st.spinner("Criando PDF profissional..."):
                df_pagamentos_pdf = df_filtrado.groupby('Forma_Pagamento')['Valor'].sum().reset_index()
                df_pagamentos_pdf = df_pagamentos_pdf.sort_values(by='Valor', ascending=False)
                df_pagamentos_pdf['Percentual'] = (df_pagamentos_pdf['Valor'] / faturamento_total) * 100 if faturamento_total > 0 else 0
                df_pagamentos_pdf['Faturamento_Formatado'] = df_pagamentos_pdf['Valor'].apply(formatar_brl)
                df_pagamentos_pdf['Percentual_Formatado'] = df_pagamentos_pdf['Percentual'].map("{:,.2f}%".format)
                df_estados_fat_pdf = df_filtrado.groupby('Estado')['Valor'].sum().nlargest(10).reset_index()
                df_estados_fat_pdf['Valor_Formatado'] = df_estados_fat_pdf['Valor'].apply(formatar_brl)
                pdf_bytes = gerar_pdf_report(df_filtrado, kpis, df_pagamentos_pdf, df_estados_fat_pdf, filtro_data)
                st.sidebar.download_button(label="📥 Baixar PDF", data=pdf_bytes, file_name=f"Relatorio_Papello_{datetime.now().strftime('%Y-%m-%d')}.pdf", mime="application/pdf")
                st.sidebar.success("Seu relatório está pronto!")

if __name__ == "__main__":
    @st.cache_resource
    def get_logo_bytes():
        if os.path.exists(LOGO_ARQUIVO_LOCAL):
            try:
                with open(LOGO_ARQUIVO_LOCAL, "rb") as f:
                    return io.BytesIO(f.read())
            except Exception as e:
                st.sidebar.error(f"Erro ao carregar o logo local: {e}")
                return None
        else:
            st.sidebar.warning(f"Arquivo '{LOGO_ARQUIVO_LOCAL}' não encontrado.")
            return None
    main()