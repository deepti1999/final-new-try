"""
WS (Wärmespeicher/Energy Storage) Calculation Engine
====================================================

Handles all WS (Energy Storage) calculations using database-driven formulas.
This engine manages:
- Daily energy storage calculations (rows 1-365)
- Annual summary calculations (row 366)
- Reference/minimum calculations (row 367)
- All column formulas for stromverbr, einspeich, ladezustand, etc.

All formulas are loaded from Formula database model for extensibility.
"""

from typing import Dict, Optional, Tuple
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class WSCalculator:
    """
    WS (Energy Storage) calculation engine using database-driven formulas.
    Manages 365 daily rows + summary rows with 30+ calculated columns.
    """
    
    def __init__(self):
        """Initialize WS calculator with FormulaService"""
        from simulator.formula_service import FormulaService
        self.formula_service = FormulaService()
        self.cache = {}
        
        # WS Constants (these could also be in database as constants)
        self.ETA_STROM_GAS = 0.65  # Power to Gas efficiency
        self.ETA_GAS_STROM = 0.585  # Gas to Power efficiency  
        self.ABREGELUNG_THRESHOLD = 1.0  # Curtailment threshold (100%)
        self.GAS_STORAGE_OFFSET = 160  # GWh offset for gas storage
    
    def get_reference_values(self, renewable_data: Dict, verbrauch_data: Dict) -> Dict:
        """
        Calculate WS reference values (row 366 baseline) from renewable and verbrauch data.
        This is equivalent to compute_ws_diagram_reference() in signals.py
        
        Args:
            renewable_data: Dict of {code: {'status_value': x, 'target_value': y}}
            verbrauch_data: Dict of {code: {'status': x, 'ziel': y}}
            
        Returns:
            Dict with reference values for row 366 calculations
        """
        # Get renewable values (prefer target for baseline)
        pv_value = renewable_data.get('1.1.2.1.2', {}).get('target_value', 0) + \
                   renewable_data.get('1.2.1.2', {}).get('target_value', 0)
        wind_value = renewable_data.get('2.1.1.2.2', {}).get('target_value', 0) + \
                     renewable_data.get('2.2.1.2', {}).get('target_value', 0)
        hydro_value = renewable_data.get('3.1.1.2', {}).get('target_value', 0)
        bio_value = renewable_data.get('4.4.1', {}).get('target_value', 0)
        ely_power_to_gas = renewable_data.get('9.2.1.5.2', {}).get('target_value', 0)
        
        # Use status if available (after WS balance), else target
        n_output_branch = renewable_data.get('9.3.1', {}).get('status_value') or \
                         renewable_data.get('9.3.1', {}).get('target_value', 0)
        n_input_branch = renewable_data.get('9.3.4', {}).get('status_value') or \
                        renewable_data.get('9.3.4', {}).get('target_value', 0)
        
        # Calculate derived values
        total_generation = pv_value + wind_value + hydro_value
        remaining_after_ely = total_generation - ely_power_to_gas
        gas_storage = n_output_branch * self.ETA_STROM_GAS
        t_value = gas_storage - self.GAS_STORAGE_OFFSET
        m_total = pv_value + wind_value + hydro_value
        n_value = m_total - ely_power_to_gas
        n_to_right = n_value - n_input_branch - n_output_branch
        stromverbr_raumwaerm_korr_366 = (t_value * self.ETA_GAS_STROM) + n_to_right + bio_value
        
        # Calculate percentages for daily distribution
        if total_generation > 0:
            percentage = remaining_after_ely / total_generation
            solarstrom_366 = pv_value * percentage
            windstrom_366 = wind_value * percentage
            sonst_kraft_konstant_366 = hydro_value * percentage
        else:
            solarstrom_366 = 0
            windstrom_366 = 0
            sonst_kraft_konstant_366 = 0
        
        # Get davon_raumw_korr reference from Verbrauch
        verbrauch_292_ziel = verbrauch_data.get('2.9.2', {}).get('ziel', 0)
        verbrauch_24_ziel = verbrauch_data.get('2.4', {}).get('ziel', 0)
        davon_raumw_korr_366 = verbrauch_292_ziel * (verbrauch_24_ziel / 100) if verbrauch_24_ziel else 0
        
        return {
            'stromverbr_raumwaerm_korr_366': stromverbr_raumwaerm_korr_366,
            'davon_raumw_korr_366': davon_raumw_korr_366,
            'pv_value': pv_value,
            'wind_value': wind_value,
            'hydro_value': hydro_value,
            'bio_value': bio_value,
            'ely_power_to_gas': ely_power_to_gas,
            'n_output_branch': n_output_branch,
            'n_input_branch': n_input_branch,
            'total_generation': total_generation,
            'remaining_after_ely': remaining_after_ely,
            'solarstrom_366': solarstrom_366,
            'windstrom_366': windstrom_366,
            'sonst_kraft_konstant_366': sonst_kraft_konstant_366,
        }
    
    def calculate_daily_row(self, row_data: Dict, reference_values: Dict) -> Dict:
        """
        Calculate all columns for a single daily WS row (1-365).
        
        Args:
            row_data: Dict with promille values and tag_im_jahr
            reference_values: Reference values from get_reference_values()
            
        Returns:
            Dict with all calculated column values
        """
        result = {}
        
        # Extract promille values
        verbrauch_promille = row_data.get('verbrauch_promille', 0)
        heizung_abwaerm_promille = row_data.get('heizung_abwaerm_promille', 0)
        wind_promille = row_data.get('wind_promille', 0)
        solar_promille = row_data.get('solar_promille', 0)
        
        # Extract reference values
        stromverbr_366 = reference_values.get('stromverbr_raumwaerm_korr_366', 0)
        davon_366 = reference_values.get('davon_raumw_korr_366', 0)
        wind_366 = reference_values.get('windstrom_366', 0)
        solar_366 = reference_values.get('solarstrom_366', 0)
        sonst_366 = reference_values.get('sonst_kraft_konstant_366', 0)
        
        # Column G: Stromverbr.
        result['stromverbr'] = stromverbr_366 * verbrauch_promille / 1000
        
        # Column H: davon Raumw.korr.
        result['davon_raumw_korr'] = davon_366 * heizung_abwaerm_promille / 365
        
        # Column J: Stromverbr. Raumwärm.Korr.
        result['stromverbr_raumwaerm_korr'] = result['stromverbr'] + result['davon_raumw_korr']
        
        # Column K: Windstrom
        result['windstrom'] = wind_promille * wind_366 / 1000
        
        # Column L: Solarstrom
        result['solarstrom'] = solar_promille * solar_366 / 1000
        
        # Column M: Sonst.Kraft(konstant)
        result['sonst_kraft_konstant'] = sonst_366 / 365
        
        # Column N: Wind+Solar Konstant
        result['wind_solar_konstant'] = result['windstrom'] + result['solarstrom'] + result['sonst_kraft_konstant']
        
        # Column O: Direktverbr. Strom
        if result['wind_solar_konstant'] <= result['stromverbr_raumwaerm_korr']:
            result['direktverbr_strom'] = result['wind_solar_konstant']
        else:
            result['direktverbr_strom'] = result['stromverbr_raumwaerm_korr']
        
        # Column P: Überschuss Strom
        if abs(result['direktverbr_strom'] - result['stromverbr_raumwaerm_korr']) < 0.01:
            result['ueberschuss_strom'] = result['wind_solar_konstant'] - result['stromverbr_raumwaerm_korr']
        else:
            result['ueberschuss_strom'] = 0
        
        # Column Q: Einspeich
        if result['stromverbr_raumwaerm_korr'] > 0:
            ratio = result['ueberschuss_strom'] / result['stromverbr_raumwaerm_korr']
            if ratio <= self.ABREGELUNG_THRESHOLD:
                result['einspeich'] = result['ueberschuss_strom'] * self.ETA_STROM_GAS
            else:
                result['einspeich'] = result['stromverbr_raumwaerm_korr'] * self.ABREGELUNG_THRESHOLD * self.ETA_STROM_GAS
        else:
            result['einspeich'] = 0
        
        # Column R: Abregelung.Z
        if result['stromverbr_raumwaerm_korr'] > 0:
            ratio = result['ueberschuss_strom'] / result['stromverbr_raumwaerm_korr']
            if ratio <= self.ABREGELUNG_THRESHOLD:
                result['abregelung_z'] = 0
            else:
                result['abregelung_z'] = result['ueberschuss_strom'] - (result['einspeich'] / self.ETA_STROM_GAS)
        else:
            result['abregelung_z'] = 0
        
        # Column S: Mangel-Last
        result['mangel_last'] = result['stromverbr_raumwaerm_korr'] - result['direktverbr_strom']
        
        return result
    
    def calculate_mangel_compensation(self, row_data: Dict, bio_value: float, sum_mangel_last: float) -> Dict:
        """
        Calculate columns T, U, V, W (Brennstoff compensation and storage discharge).
        
        Args:
            row_data: Dict with current row's mangel_last
            bio_value: Bio energy value from reference
            sum_mangel_last: Total mangel_last from row 366
            
        Returns:
            Dict with T, U, V, W column values
        """
        result = {}
        mangel_last = row_data.get('mangel_last', 0)
        
        if sum_mangel_last > 0:
            # Column T: Brennstoff-Ausgleichs-Strom
            result['brennstoff_ausgleichs_strom'] = (bio_value / sum_mangel_last) * mangel_last
            
            # Column U: Speicher-Ausgl-Strom
            result['speicher_ausgl_strom'] = mangel_last - result['brennstoff_ausgleichs_strom']
            
            # Column V: Ausspeich.Rückverstr.
            result['ausspeich_rueckverstr'] = result['speicher_ausgl_strom'] / self.ETA_GAS_STROM
            
            # Column W: Ausspeich. Gas
            result['ausspeich_gas'] = 0
        else:
            result['brennstoff_ausgleichs_strom'] = 0
            result['speicher_ausgl_strom'] = 0
            result['ausspeich_rueckverstr'] = 0
            result['ausspeich_gas'] = 0
        
        return result
    
    def calculate_cumulative_storage(self, row_data: Dict, previous_ladezust: float) -> Dict:
        """
        Calculate cumulative storage columns (X, Y, Z, AA, AB).
        
        Args:
            row_data: Dict with einspeich, ausspeich values
            previous_ladezust: Previous row's ladezust_burtto value
            
        Returns:
            Dict with cumulative storage values
        """
        result = {}
        
        einspeich = row_data.get('einspeich', 0)
        ausspeich_rueck = row_data.get('ausspeich_rueckverstr', 0)
        ausspeich_gas = row_data.get('ausspeich_gas', 0)
        
        # Column X: Ladezust.Burtto (cumulative)
        result['ladezust_burtto'] = previous_ladezust + einspeich - ausspeich_rueck - ausspeich_gas
        
        return result
    
    def calculate_absolute_storage(self, row_data: Dict, ladezust_367: float, ladezustand_netto_367: float) -> Dict:
        """
        Calculate absolute storage levels (Y, Z, AA, AB).
        
        Args:
            row_data: Dict with ladezust_burtto, ladezustand_netto
            ladezust_367: Reference value from row 367 (minimum)
            ladezustand_netto_367: Netto reference from row 367
            
        Returns:
            Dict with absolute storage values
        """
        result = {}
        
        ladezust_burtto = row_data.get('ladezust_burtto', 0)
        ladezustand_netto = row_data.get('ladezustand_netto', 0)
        
        # Column Y: LadezustandAbs. vorl.TL
        result['ladezustand_abs_vorl_tl'] = ladezust_burtto - ladezust_367
        
        # Column Z: Selbstentl.
        result['selbstentl'] = result['ladezustand_abs_vorl_tl'] * 0  # Currently 0
        
        # Column AB: Ladezustand Abs.
        result['ladezustand_abs'] = ladezustand_netto - ladezustand_netto_367
        
        return result
    
    def calculate_netto_storage(self, row_data: Dict, previous_netto: float) -> Dict:
        """
        Calculate netto storage (AA) - cumulative with selbstentl.
        
        Args:
            row_data: Dict with einspeich, ausspeich, selbstentl
            previous_netto: Previous row's ladezustand_netto value
            
        Returns:
            Dict with netto storage value
        """
        result = {}
        
        einspeich = row_data.get('einspeich', 0)
        ausspeich_rueck = row_data.get('ausspeich_rueckverstr', 0)
        ausspeich_gas = row_data.get('ausspeich_gas', 0)
        selbstentl = row_data.get('selbstentl', 0)
        
        # Column AA: Ladezustand Netto (cumulative)
        result['ladezustand_netto'] = previous_netto + einspeich - ausspeich_rueck - ausspeich_gas - selbstentl
        
        return result
