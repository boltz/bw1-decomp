#ifndef BW1_DECOMP_LH3D_SKY_INCLUDED_H
#define BW1_DECOMP_LH3D_SKY_INCLUDED_H

#include <stdint.h> /* For uint16_t, uint8_t */

struct LH3DColor;
struct LHMatrix;
struct LHPoint;

class LH3DSky
{
public:
	// Original Mac import
	// BW1W120 00fa2760 BW1M119 012d3540 (LHCombined Release)
	static int g_b_we_are_inside_citadel;

	// BW1W120 00869690 BW1M119 010b2170 (LHCombined Release)
	static LH3DColor Interpolate444Colour(uint16_t from, uint16_t to, int amount);
	// BW1W120 00869850 BW1M119 01038370 (LHCombined Release)
	static void CalculateColours();
	// BW1W120 00869fa0 BW1M119 010b2070 (LHCombined Release)
	static void SetDayNightTimes(float night, float dusk_start, float dusk_end, float day);
	// BW1W120 00869fd0 BW1M119 01036b80 (LHCombined Release)
	static float ConvertTime(float time, float from_night, float from_dusk_start, float from_dusk_end, float from_day,
	                         float to_night, float to_dusk_start, float to_dusk_end, float to_day);
	// BW1W120 0086a110 BW1M119 01036cd0 (LHCombined Release)
	static float OldSkoolTime2Time(float time);
	// BW1W120 0086a160 BW1M119 01037b10 (LHCombined Release)
	static float Time2OldSkoolTime(float time);
	// BW1W120 0086a1b0 BW1M119 01033e10 (LHCombined Release)
	static float Time2SkyType(float time);
	// BW1W120 0086a270 BW1M119 010b1b80 (LHCombined Release)
	static void ForceTime(float time);
	// BW1W120 0086a2c0 BW1M119 0103b470 (LHCombined Release)
	static void SetTime(float time);
	// BW1W120 0086a330 BW1M119 01038150 (LHCombined Release)
	static void Update();
	// BW1W120 0086a3b0 BW1M119 010b12a0 (LHCombined Release)
	static void Init(float time, float overcast);
	// BW1W120 0086a770 BW1M119 010b11a0 (LHCombined Release)
	static void Close();
	// BW1W120 0086a7f0 BW1M119 010b1030 (LHCombined Release)
	static float CalcMoonRot(int& changed);
	// BW1W120 0086a890 BW1M119 010b0e00 (LHCombined Release)
	static void CalcMoonPhase();
	// BW1W120 0086a930 BW1M119 010b0910 (LHCombined Release)
	static void DrawMoonPost(LH3DColor& colour, LHMatrix& matrix, LHMatrix& moon_matrix);
	// BW1W120 0086ac60 BW1M119 010b02d0 (LHCombined Release)
	static void CalcMoonMat(LHPoint& pos, LHMatrix& matrix, LHMatrix& moon_matrix);
	// BW1W120 0086b010 BW1M119 01014310 (LHCombined Release)
	static void Draw();
	// BW1W120 0086b6b0 BW1M119 01016380 (LHCombined Release)
	static void DrawSky(int index, int alpha, int colour, int specular);
	// BW1W120 0086b7f0 BW1M119 010afeb0 (LHCombined Release)
	static void CalculateTextures(float sky_type, int start_y, int num_lines);
	// BW1W120 0086b9a0 BW1M119 010afa10 (LHCombined Release)
	static void Interpolate555Texture(uint16_t* dest, uint16_t* source1, uint16_t* source2, uint8_t amount, int width,
	                                  int start_y, int num_lines, int pitch);
	// BW1W120 0086bb60 BW1M119 01014060 (LHCombined Release)
	static void PostDrawSun();
	// BW1W120 0086bd00 BW1M119 01033ee0 (LHCombined Release)
	static float GetSunVisibility();
	// BW1W120 0086c020 BW1M119 01010330 (LHCombined Release)
	static float GetSunAltitude();
	// BW1W120 0086c140 BW1M119 010af4e0 (LHCombined Release)
	static void DrawSun();
	// BW1W120 0086c220 BW1M119 010af360 (LHCombined Release)
	static float ComputeAlphaEclairagePublique();
};

#endif /* BW1_DECOMP_LH3D_SKY_INCLUDED_H */
