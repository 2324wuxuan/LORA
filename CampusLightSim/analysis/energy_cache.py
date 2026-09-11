"""Shared, bounded UI cache for the full 486,720-point daily calculation."""
import hashlib
import json
import streamlit as st
from config import DEVICES, ENVIRONMENT, LIGHTING_RULES, ENERGY
from analysis.energy import compare_simulated_daily_energy

_MODEL_KEY = hashlib.sha256(json.dumps([DEVICES, ENVIRONMENT, LIGHTING_RULES, ENERGY],
                                       sort_keys=True).encode()).hexdigest()


@st.cache_data(max_entries=8, show_spinner="正在逐一计算全部照明控制节点的日能耗…")
def _daily(day, model_key):
    return compare_simulated_daily_energy(day)


def daily_energy_for_ui(day):
    return _daily(day, _MODEL_KEY)
