#ifndef BW1_DECOMP_LH3D_SKY_INCLUDED_H
#define BW1_DECOMP_LH3D_SKY_INCLUDED_H

#include <stdint.h>

#include <re_common.h>

#include "LH3DColor.h"

class LH3DObject;
struct LH3DMesh;
struct LHMatrix;
struct LHPoint;

#define HOURS_PER_DAY                24.0f
#define HOURS_PER_HALF_DAY           (HOURS_PER_DAY / 2.0f)
#define SKY_TEXTURE_HEIGHT_LOW       0x80
#define SKY_TEXTURE_HEIGHT           0x100
#define SKY_TEXTURE_UPDATE_LINES     0x20
#define SKY_TYPE_CHANGE_THRESHOLD    0.03f
#define LH3D_SKY_LIGHT_COLOUR_COUNT  8
#define LH3D_SKY_MOON_COLOUR         5
#define LH3D_SKY_MOON_QUAD_SIZE      500.0f
#define LH3D_SKY_MOON_UV_MIN         0.25f
#define LH3D_SKY_MOON_UV_MAX         0.49375f
#define LH3D_SKY_MOON_RED_DIVISOR    6
#define LH3D_SKY_MOON_GREEN_DIVISOR  5
#define LH3D_SKY_MOON_BLUE_SHIFT     2
#define LH3D_SKY_MOON_VERTEX_COUNT   4
#define LH3D_SKY_MOON_TRIANGLE_COUNT 2
#define LH3D_SKY_MOON_FOG_SCALE      0.5f
#define LH3D_SKY_MOON_FOG_OFFSET     110.0f
#define LH3D_SKY_MOON_FOG_MAX        200
#define LH3D_SKY_FOG_SCALE           8.0f
#define LH3D_SKY_TOP_SCALE           0.5f
#define LH3D_SKY_TOP_OFFSET          0.5f
#define LH3D_SKY_TOP_GREEN_SCALE     1.7f
#define LH3D_SKY_TOP_BLUE_SCALE      1.5f
#define LH3D_ATMOS_ALIGNMENT_FADE    150
#define LH3D_SKY_ALPHA_MAX           255.0f

enum SKY_TYPE
{
	SKY_TYPE_DAY,
	SKY_TYPE_DUSK,
	SKY_TYPE_NIGHT,
	SKY_TYPE_LAST,
};

enum SKY_ALIGNMENT
{
	SKY_ALIGNMENT_GOOD,
	SKY_ALIGNMENT_NEUTRAL,
	SKY_ALIGNMENT_EVIL,
	SKY_ALIGNMENT_LAST,
};

class LH3DSky
{
public:
	// Original Mac import
	// BW1W120 00fa2760 BW1M119 012d3540 (LHCombined Release)
	static int g_b_we_are_inside_citadel;
	// BW1W120 00c395a8 BW1M119 011d11b8 (LHCombined Release)
	static float g_alpha_sun;
	// BW1W120 00c395b0 BW1M119 011d11c0 (LHCombined Release)
	static float ONIGHT_FULL_TIME;
	// BW1W120 00c395b4 BW1M119 011d11c4 (LHCombined Release)
	static float ODUSK_START_TIME;
	// BW1W120 00c395b8 BW1M119 011d11c8 (LHCombined Release)
	static float ODUSK_END_TIME;
	// BW1W120 00c395bc BW1M119 011d11cc (LHCombined Release)
	static float ODAY_FULL_TIME;
	// BW1W120 00fa2694 BW1M119 012d3514 (LHCombined Release)
	static float DAY_FULL_TIME;
	// BW1W120 00fa2698 BW1M119 012d3518 (LHCombined Release)
	static float DUSK_END_TIME;
	// BW1W120 00fa269c BW1M119 012d351c (LHCombined Release)
	static float DUSK_START_TIME;
	// BW1W120 00fa26a0 BW1M119 012d3520 (LHCombined Release)
	static float NIGHT_FULL_TIME;
	// BW1W120 00fa26b8 BW1M119 012d3544 (LHCombined Release)
	static int cury;
	// BW1W120 00fa26bc BW1M119 012d3548 (LHCombined Release)
	static float newst;
	// BW1W120 00fa26c0 BW1M119 012d354c (LHCombined Release)
	static float curst;
	// BW1W120 00fa26c4 BW1M119 012d3550 (LHCombined Release)
	static float curtime;

	// BW1W120 00fa26a4 BW1M119 012d3528 (LHCombined Release)
	static LH3DColor topcol;
	// BW1W120 00fa26c8 BW1M119 012d355c (LHCombined Release)
	static LH3DColor lightcols[LH3D_SKY_LIGHT_COLOUR_COUNT];
	// BW1W120 00fa26e8 BW1M119 012d357c (LHCombined Release)
	static void* bitmaps[SKY_TYPE_LAST][SKY_ALIGNMENT_LAST];
	// BW1W120 00fa2710 BW1M119 012d35a0 (LHCombined Release)
	static LHPoint g_sun_pos;
	// BW1W120 00fa271c BW1M119 012d35ac (LHCombined Release)
	static LH3DObject* sunobj;
	// BW1W120 00fa2720 BW1M119 012d35b0 (LHCombined Release)
	static LH3DMesh* sun;
	// BW1W120 00fa2724 BW1M119 012d35b8 (LHCombined Release)
	static float moonphase;
	// BW1W120 00fa2728 BW1M119 012d35bc (LHCombined Release)
	static LH3DObject* moonobj;
	// BW1W120 00fa272c BW1M119 012d35c0 (LHCombined Release)
	static LH3DMesh* moon;
	// BW1W120 00fa2730 BW1M119 012d35c4 (LHCombined Release)
	static LH3DObject* sky;
	// BW1W120 00fa2734 BW1M119 012d35c8 (LHCombined Release)
	static LH3DMesh* skymesh;
	// BW1W120 00fa2750 BW1M119 012d35b4 (LHCombined Release)
	static float moonsize;
	// BW1W120 00fa2754 BW1M119 012d3558 (LHCombined Release)
	static float overcast;
	// BW1W120 00fa2758 BW1M119 012d3554 (LHCombined Release)
	static float evil;
	// BW1W120 00fa275c BW1M119 012d3524 (LHCombined Release)
	static bool32_t LightningGlow;

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
	static void Init(float alignment, float time);
	// BW1W120 0086a770 BW1M119 010b11a0 (LHCombined Release)
	static void Close();
	// BW1W120 0086a7f0 BW1M119 010b1030 (LHCombined Release)
	static float CalcMoonRot(int& changed);
	// BW1W120 0086a890 BW1M119 010b0e00 (LHCombined Release)
	static void CalcMoonPhase();
	// BW1W120 0086a930 BW1M119 010b0910 (LHCombined Release)
	static void DrawMoonPost(LH3DColor& colour, LHMatrix& quad_matrix, LHMatrix& moon_matrix);
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
