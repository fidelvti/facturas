from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from facturas.dashboard_data import (
    get_agua_data,
    get_gas_data,
    get_luz_data,
    get_pagatelia_data,
    get_payroll_data,
    period_start_date_from_display,
)


DATABASE_PATH = Path("data/facturas.sqlite3")


def main() -> None:
    st.set_page_config(page_title="Facturas", layout="wide")
    st.title("Facturas")

    page = st.sidebar.radio(
        "Área",
        ["Agua", "Gas", "Luz", "Nóminas", "Pagatelia"],
    )

    if page == "Agua":
        _agua_page()
    elif page == "Gas":
        _gas_page()
    elif page == "Luz":
        _luz_page()
    elif page == "Nóminas":
        _payroll_page()
    else:
        _pagatelia_page()


def _agua_page() -> None:
    st.header("Agua")
    data = _filtered_dataframe(get_agua_data(DATABASE_PATH), key="agua_years")
    _show_table(data)
    if not data.empty:
        st.subheader("Evolución del consumo de agua")
        st.line_chart(_chart_dataframe(data), x="Periodo fecha", y="Consumo (m3)")
        st.subheader("Evolución del importe")
        st.line_chart(_chart_dataframe(data), x="Periodo fecha", y="Importe total")


def _gas_page() -> None:
    st.header("Gas")
    data = get_gas_data(DATABASE_PATH)
    potencia, consumo, otros = st.tabs(["Potencia / plazo fijo", "Consumo", "Otros"])

    with potencia:
        df = _filtered_dataframe(data["potencia"], key="gas_potencia_years")
        _show_table(df, column_config={
            "Plazo fijo": st.column_config.NumberColumn(format="%.6f"),
            "Total": st.column_config.NumberColumn(format="%.2f"),
        })
        if not df.empty:
            st.subheader("Evolución del plazo fijo")
            st.line_chart(_chart_dataframe(df), x="Periodo fecha", y="Plazo fijo")

    with consumo:
        df = _filtered_dataframe(data["consumo"], key="gas_consumo_years")
        _show_table(df, column_config={
            "Importe unitario": st.column_config.NumberColumn(format="%.6f"),
            "Total": st.column_config.NumberColumn(format="%.2f"),
        })
        if not df.empty:
            st.subheader("Evolución del precio unitario de consumo")
            st.line_chart(_chart_dataframe(df), x="Periodo fecha", y="Importe unitario")

    with otros:
        _show_table(_filtered_dataframe(data["otros"], key="gas_otros_years"))


def _luz_page() -> None:
    st.header("Luz")
    data = get_luz_data(DATABASE_PATH)
    potencia, consumo, otros = st.tabs(["Potencia", "Consumo / energía", "Otros"])

    with potencia:
        df = _filtered_dataframe(data["potencia"], key="luz_potencia_years")
        _show_table(df, column_config={
            "Precio unitario": st.column_config.NumberColumn(format="%.6f"),
            "Total": st.column_config.NumberColumn(format="%.2f"),
        })
        if not df.empty:
            st.subheader("Evolución del precio de potencia")
            st.line_chart(_chart_dataframe(df), x="Periodo fecha", y="Precio unitario")

    with consumo:
        df = _filtered_dataframe(data["consumo"], key="luz_consumo_years")
        _show_table(df, column_config={
            "Precio unitario": st.column_config.NumberColumn(format="%.6f"),
            "Total": st.column_config.NumberColumn(format="%.2f"),
        })
        if not df.empty:
            st.subheader("Evolución del precio de energía")
            st.line_chart(_chart_dataframe(df), x="Periodo fecha", y="Precio unitario")

    with otros:
        _show_table(
            _filtered_dataframe(data["otros"], key="luz_otros_years"),
            column_config={
                "Impuesto electricidad (%)": st.column_config.NumberColumn(format="%.6f"),
            },
        )


def _payroll_page() -> None:
    st.header("Nóminas")
    _show_table(_filtered_dataframe(get_payroll_data(DATABASE_PATH), key="payroll_years"))


def _pagatelia_page() -> None:
    st.header("Pagatelia")
    _show_table(
        _filtered_dataframe(get_pagatelia_data(DATABASE_PATH), key="pagatelia_years"),
        column_config={
            "Importe": st.column_config.NumberColumn(format="%.2f"),
            "Factura": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def _filtered_dataframe(rows: list[dict[str, object]], *, key: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty or "Periodo" not in df.columns:
        return df

    years = sorted({str(value)[-4:] for value in df["Periodo"] if value})
    selected = st.multiselect("Años", years, default=years, key=key)
    if selected:
        df = df[df["Periodo"].astype(str).str[-4:].isin(selected)]
    return df


def _chart_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    chart = df.copy()
    chart["Periodo fecha"] = pd.to_datetime(
        chart["Periodo"].map(period_start_date_from_display)
    )
    return chart.sort_values("Periodo fecha", kind="stable")


def _show_table(
    df: pd.DataFrame,
    *,
    column_config: dict[str, object] | None = None,
) -> None:
    if df.empty:
        st.info("No hay datos disponibles.")
        return
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config=column_config,
    )


if __name__ == "__main__":
    main()
