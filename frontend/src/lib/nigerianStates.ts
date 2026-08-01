/**
 * Nigerian states, used for PAYE routing.
 *
 * PAYE is remitted to the State Internal Revenue Service of the employee's
 * state of *residence* — not to FIRS and not to the state the employer is
 * registered in. Mirrors backend/apps/payroll/constants.py.
 */
export const NIGERIAN_STATES: { code: string; label: string }[] = [
  { code: 'AB', label: 'Abia' },
  { code: 'AD', label: 'Adamawa' },
  { code: 'AK', label: 'Akwa Ibom' },
  { code: 'AN', label: 'Anambra' },
  { code: 'BA', label: 'Bauchi' },
  { code: 'BY', label: 'Bayelsa' },
  { code: 'BE', label: 'Benue' },
  { code: 'BO', label: 'Borno' },
  { code: 'CR', label: 'Cross River' },
  { code: 'DE', label: 'Delta' },
  { code: 'EB', label: 'Ebonyi' },
  { code: 'ED', label: 'Edo' },
  { code: 'EK', label: 'Ekiti' },
  { code: 'EN', label: 'Enugu' },
  { code: 'GO', label: 'Gombe' },
  { code: 'IM', label: 'Imo' },
  { code: 'JI', label: 'Jigawa' },
  { code: 'KD', label: 'Kaduna' },
  { code: 'KN', label: 'Kano' },
  { code: 'KT', label: 'Katsina' },
  { code: 'KE', label: 'Kebbi' },
  { code: 'KO', label: 'Kogi' },
  { code: 'KW', label: 'Kwara' },
  { code: 'LA', label: 'Lagos' },
  { code: 'NA', label: 'Nasarawa' },
  { code: 'NI', label: 'Niger' },
  { code: 'OG', label: 'Ogun' },
  { code: 'ON', label: 'Ondo' },
  { code: 'OS', label: 'Osun' },
  { code: 'OY', label: 'Oyo' },
  { code: 'PL', label: 'Plateau' },
  { code: 'RI', label: 'Rivers' },
  { code: 'SO', label: 'Sokoto' },
  { code: 'TA', label: 'Taraba' },
  { code: 'YO', label: 'Yobe' },
  { code: 'ZA', label: 'Zamfara' },
  { code: 'FC', label: 'FCT Abuja' },
]

export const STATE_LABEL: Record<string, string> = Object.fromEntries(
  NIGERIAN_STATES.map((s) => [s.code, s.label]),
)
