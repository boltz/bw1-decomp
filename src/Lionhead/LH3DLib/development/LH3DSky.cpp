#include "LH3DSky.h"

#include <math.h>

#include <re_common.h>

#include "LH3DAtmos.h"
#include "LH3DColor.h"
#include "LH3DMaterial.h"
#include "LH3DMesh.h"
#include "LH3DObject.h"
#include "LH3DTech.h"
#include "LH3DTexture.h"
#include "LHMatrix.h"
#include "LHPoint.h"

int         LH3DSky::g_b_we_are_inside_citadel;
float       LH3DSky::g_alpha_sun = LH3D_SKY_ALPHA_MAX;
float       LH3DSky::ONIGHT_FULL_TIME = 3.5f;
float       LH3DSky::ODUSK_START_TIME = 7.5f;
float       LH3DSky::ODUSK_END_TIME = 8.0f;
float       LH3DSky::ODAY_FULL_TIME = 8.5f;
float       LH3DSky::DAY_FULL_TIME;
float       LH3DSky::DUSK_END_TIME;
float       LH3DSky::DUSK_START_TIME;
float       LH3DSky::NIGHT_FULL_TIME;
int         LH3DSky::cury;
float       LH3DSky::newst;
float       LH3DSky::curst;
float       LH3DSky::curtime;
LH3DColor   LH3DSky::topcol;
LH3DColor   LH3DSky::lightcols[LH3D_SKY_LIGHT_COLOUR_COUNT];
void*       LH3DSky::bitmaps[SKY_TYPE_LAST][SKY_ALIGNMENT_LAST];
LHPoint     LH3DSky::g_sun_pos;
LH3DObject* LH3DSky::sunobj;
LH3DMesh*   LH3DSky::sun;
float       LH3DSky::moonphase;
LH3DObject* LH3DSky::moonobj;
LH3DMesh*   LH3DSky::moon;
LH3DObject* LH3DSky::sky;
LH3DMesh*   LH3DSky::skymesh;
float       LH3DSky::moonsize;
float       LH3DSky::overcast;
float       LH3DSky::evil;
bool32_t    LH3DSky::LightningGlow;

int   fog_fade;
float fog_blue;
float fog_green;
float fog_red;

LH3DTexture*  sky_texture[SKY_TYPE_LAST];
LH3DMaterial* sky_material[SKY_TYPE_LAST];

bool32_t g_jc_caca_first_init_sky = true;
int      g_fade;
bool     moonflip;

void LH3DSky::SetDayNightTimes(float night, float dusk_start, float dusk_end, float day)
{
	NIGHT_FULL_TIME = night;
	DUSK_START_TIME = dusk_start;
	DUSK_END_TIME = dusk_end;
	DAY_FULL_TIME = day;
}

float LH3DSky::ConvertTime(float time, float from_night, float from_dusk_start, float from_dusk_end, float from_day,
                           float to_night, float to_dusk_start, float to_dusk_end, float to_day)
{
	bool isAfternoon = false;
	if (time > LH3D_SKY_HOURS_PER_HALF_DAY)
	{
		time = LH3D_SKY_HOURS_PER_DAY - time;
		isAfternoon = true;
	}

	SKY_TIME_INTERVAL interval;
	float             fraction;
	if (time < from_night)
	{
		interval = SKY_TIME_INTERVAL_NIGHT;
		fraction = time / from_night;
	}
	else if (time < from_dusk_start)
	{
		interval = SKY_TIME_INTERVAL_NIGHT_TO_DUSK;
		fraction = (time - from_night) / (from_dusk_start - from_night);
	}
	else if (time < from_dusk_end)
	{
		interval = SKY_TIME_INTERVAL_DUSK;
		fraction = (time - from_dusk_start) / (from_dusk_end - from_dusk_start);
	}
	else if (time < from_day)
	{
		interval = SKY_TIME_INTERVAL_DUSK_TO_DAY;
		fraction = (time - from_dusk_end) / (from_day - from_dusk_end);
	}
	else
	{
		interval = SKY_TIME_INTERVAL_DAY;
		fraction = (time - from_day) / (LH3D_SKY_HOURS_PER_HALF_DAY - from_day);
	}

	switch (interval)
	{
	case SKY_TIME_INTERVAL_NIGHT:
		time = fraction * to_night;
		break;
	case SKY_TIME_INTERVAL_NIGHT_TO_DUSK:
		time = to_night + fraction * (to_dusk_start - to_night);
		break;
	case SKY_TIME_INTERVAL_DUSK:
		time = to_dusk_start + fraction * (to_dusk_end - to_dusk_start);
		break;
	case SKY_TIME_INTERVAL_DUSK_TO_DAY:
		time = to_dusk_end + fraction * (to_day - to_dusk_end);
		break;
	case SKY_TIME_INTERVAL_DAY:
		time = to_day + fraction * (LH3D_SKY_HOURS_PER_HALF_DAY - to_day);
		break;
	}

	if (isAfternoon)
	{
		time = LH3D_SKY_HOURS_PER_DAY - time;
	}
	return time;
}

float LH3DSky::OldSkoolTime2Time(float time)
{
	return ConvertTime(time, ONIGHT_FULL_TIME, ODUSK_START_TIME, ODUSK_END_TIME, ODAY_FULL_TIME, NIGHT_FULL_TIME,
	                   DUSK_START_TIME, DUSK_END_TIME, DAY_FULL_TIME);
}

float LH3DSky::Time2OldSkoolTime(float time)
{
	return ConvertTime(time, NIGHT_FULL_TIME, DUSK_START_TIME, DUSK_END_TIME, DAY_FULL_TIME, ONIGHT_FULL_TIME,
	                   ODUSK_START_TIME, ODUSK_END_TIME, ODAY_FULL_TIME);
}

float LH3DSky::Time2SkyType(float time)
{
	float skyType = SKY_TYPE_DAY;
	if (time > LH3D_SKY_HOURS_PER_HALF_DAY)
	{
		time = LH3D_SKY_HOURS_PER_DAY - time;
	}
	if (time < NIGHT_FULL_TIME)
	{
		skyType = SKY_TYPE_NIGHT;
	}
	else if (time < DUSK_START_TIME)
	{
		skyType = SKY_TYPE_NIGHT - (time - NIGHT_FULL_TIME) / (DUSK_START_TIME - NIGHT_FULL_TIME);
	}
	else if (time < DUSK_END_TIME)
	{
		skyType = SKY_TYPE_DUSK;
	}
	else if (time < DAY_FULL_TIME)
	{
		skyType = SKY_TYPE_DUSK - (time - DUSK_END_TIME) / (DAY_FULL_TIME - DUSK_END_TIME);
	}
	return skyType;
}

void LH3DSky::ForceTime(float time)
{
	SetTime(time);
	curst = newst;
	cury = 0;
	CalculateTextures(newst, 0, LH3DTexture::g_b_use_low_res ? SKY_TEXTURE_HEIGHT_LOW : SKY_TEXTURE_HEIGHT);
	CalculateColours();
}

void LH3DSky::SetTime(float time)
{
	while (time < 0.0f)
	{
		time += LH3D_SKY_HOURS_PER_DAY;
	}
	while (time >= LH3D_SKY_HOURS_PER_DAY)
	{
		time -= LH3D_SKY_HOURS_PER_DAY;
	}
	curtime = time;
	newst = Time2SkyType(time);
}

void LH3DSky::Update()
{
	CalculateColours();
	int textureHeight = LH3DTexture::g_b_use_low_res ? SKY_TEXTURE_HEIGHT_LOW : SKY_TEXTURE_HEIGHT;
	if (cury >= textureHeight)
	{
		if (fabs(newst - curst) > SKY_TYPE_CHANGE_THRESHOLD)
		{
			curst = newst;
			cury = 0;
		}
		if (cury >= textureHeight)
		{
			return;
		}
	}
	CalculateTextures(curst, cury, SKY_TEXTURE_UPDATE_LINES);
	cury += SKY_TEXTURE_UPDATE_LINES;
}

void LH3DSky::DrawMoonPost(LH3DColor& colour, LHMatrix& quad_matrix, LHMatrix& moon_matrix)
{
	LH3DAtmos::v_idx[0][0] = 0;
	LH3DAtmos::v_idx[0][1] = 1;
	LH3DAtmos::v_idx[0][2] = 3;
	LH3DAtmos::v_idx[0][3] = 3;
	LH3DAtmos::v_idx[0][4] = 2;
	LH3DAtmos::v_idx[0][5] = 0;

	LH3DAtmos::v_uv[0][0] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][1] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][2] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[0][3] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][4] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][5] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[0][6] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[0][7] = LH3D_SKY_MOON_UV_MAX;

	LH3DColor glowColour = colour;
	glowColour.r = (uint8_t)((int)glowColour.r / LH3D_SKY_MOON_RED_DIVISOR);
	glowColour.g = (uint8_t)((int)glowColour.g / LH3D_SKY_MOON_GREEN_DIVISOR);
	glowColour.b >>= LH3D_SKY_MOON_BLUE_SHIFT;

	LH3DAtmos::v_col[0][0] = glowColour;
	LH3DAtmos::v_col[0][1] = glowColour;
	LH3DAtmos::v_col[0][2] = glowColour;
	LH3DAtmos::v_col[0][3] = glowColour;

	LHPoint& lowerLeft = LH3DAtmos::v_pnt[0][0];
	lowerLeft.x =
		quad_matrix.GetPos().x - (quad_matrix.GetVectorY().x + quad_matrix.GetVectorX().x) * LH3D_SKY_MOON_QUAD_SIZE;
	lowerLeft.y =
		quad_matrix.GetPos().y - (quad_matrix.GetVectorY().y + quad_matrix.GetVectorX().y) * LH3D_SKY_MOON_QUAD_SIZE;
	lowerLeft.z =
		quad_matrix.GetPos().z - (quad_matrix.GetVectorY().z + quad_matrix.GetVectorX().z) * LH3D_SKY_MOON_QUAD_SIZE;
	LHPoint& lowerRight = LH3DAtmos::v_pnt[0][1];
	lowerRight.x =
		(quad_matrix.GetVectorX().x * LH3D_SKY_MOON_QUAD_SIZE - quad_matrix.GetVectorY().x * LH3D_SKY_MOON_QUAD_SIZE) +
		quad_matrix.GetPos().x;
	lowerRight.y =
		(quad_matrix.GetVectorX().y * LH3D_SKY_MOON_QUAD_SIZE - quad_matrix.GetVectorY().y * LH3D_SKY_MOON_QUAD_SIZE) +
		quad_matrix.GetPos().y;
	lowerRight.z =
		(quad_matrix.GetVectorX().z * LH3D_SKY_MOON_QUAD_SIZE - quad_matrix.GetVectorY().z * LH3D_SKY_MOON_QUAD_SIZE) +
		quad_matrix.GetPos().z;
	LHPoint& upperLeft = LH3DAtmos::v_pnt[0][2];
	upperLeft.x =
		(quad_matrix.GetVectorY().x * LH3D_SKY_MOON_QUAD_SIZE - quad_matrix.GetVectorX().x * LH3D_SKY_MOON_QUAD_SIZE) +
		quad_matrix.GetPos().x;
	upperLeft.y =
		(quad_matrix.GetVectorY().y * LH3D_SKY_MOON_QUAD_SIZE - quad_matrix.GetVectorX().y * LH3D_SKY_MOON_QUAD_SIZE) +
		quad_matrix.GetPos().y;
	upperLeft.z =
		(quad_matrix.GetVectorY().z * LH3D_SKY_MOON_QUAD_SIZE - quad_matrix.GetVectorX().z * LH3D_SKY_MOON_QUAD_SIZE) +
		quad_matrix.GetPos().z;
	LHPoint& upperRight = LH3DAtmos::v_pnt[0][3];
	upperRight.x =
		quad_matrix.GetPos().x + (quad_matrix.GetVectorY().x + quad_matrix.GetVectorX().x) * LH3D_SKY_MOON_QUAD_SIZE;
	upperRight.y =
		quad_matrix.GetPos().y + (quad_matrix.GetVectorY().y + quad_matrix.GetVectorX().y) * LH3D_SKY_MOON_QUAD_SIZE;
	upperRight.z =
		quad_matrix.GetPos().z + (quad_matrix.GetVectorY().z + quad_matrix.GetVectorX().z) * LH3D_SKY_MOON_QUAD_SIZE;

	LH3DTech::Draw3DWorldTriangle(LH3D_SKY_MOON_VERTEX_COUNT, LH3DAtmos::v_pnt[0], LH3DAtmos::v_col[0],
	                              LH3DAtmos::v_uv[0], LH3D_SKY_MOON_TRIANGLE_COUNT, LH3DAtmos::v_idx[0],
	                              LH3DAtmos::AdditiveMaterial, false);

	moonobj->matrix.Set(moon_matrix);
	moonobj->SetColorSpecular(colour.GetColor(), 0);
	moonobj->SetDrawWithGlobalAlpha(true);
	if (!moonflip)
	{
		moonobj->Draw();
		moonobj->SetColorSpecular(colour.GetColor(), 0);
		moonobj->SetDrawWithGlobalAlpha(true);
		moonobj->DrawUnderWater();
	}
}
