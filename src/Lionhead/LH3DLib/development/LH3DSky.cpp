#include "LH3DSky.h"

#include <math.h>
#include <string.h>

#include <re_common.h>

#include "LH3DAtmos.h"
#include "LH3DColor.h"
#include "LH3DIsland.h"
#include "LH3DLevelOfDetail.h"
#include "LH3DMaterial.h"
#include "LH3DMem.h"
#include "LH3DMesh.h"
#include "LH3DObject.h"
#include "LH3DPrimitive.h"
#include "LH3DRender.h"
#include "LH3DSubMesh.h"
#include "LH3DTech.h"
#include "LH3DTexture.h"
#include "LHMatrix.h"
#include "LHPoint.h"

#include <Lionhead/LHFile/ver3.0/LHOSFile.h>

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
LH3DColor   LH3DSky::lightcols[8];
void*       LH3DSky::bitmaps[3][3];
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

LH3DTexture*  sky_texture[3];
LH3DMaterial* sky_material[3];

bool32_t g_jc_caca_first_init_sky = true;
int      g_fade;
bool     moonflip;

static char g_sky_texture_name[0x100];

// BW1W120 00822190 BW1M119 010a4860 (LHCombined Release)
void* LoadTextureCitadel(char* name, unsigned char* data);

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
	if (time > HOURS_PER_HALF_DAY)
	{
		time = HOURS_PER_DAY - time;
		isAfternoon = true;
	}

	int   interval;
	float fraction;
	if (time < from_night)
	{
		interval = 0;
		fraction = time / from_night;
	}
	else if (time < from_dusk_start)
	{
		interval = 1;
		fraction = (time - from_night) / (from_dusk_start - from_night);
	}
	else if (time < from_dusk_end)
	{
		interval = 2;
		fraction = (time - from_dusk_start) / (from_dusk_end - from_dusk_start);
	}
	else if (time < from_day)
	{
		interval = 3;
		fraction = (time - from_dusk_end) / (from_day - from_dusk_end);
	}
	else
	{
		interval = 4;
		fraction = (time - from_day) / (HOURS_PER_HALF_DAY - from_day);
	}

	float result;
	switch (interval)
	{
	case 0:
		result = fraction * to_night;
		break;
	case 1:
		result = to_night + fraction * (to_dusk_start - to_night);
		break;
	case 2:
		result = to_dusk_start + fraction * (to_dusk_end - to_dusk_start);
		break;
	case 3:
		result = to_dusk_end + fraction * (to_day - to_dusk_end);
		break;
	case 4:
		result = to_day + fraction * (HOURS_PER_HALF_DAY - to_day);
		break;
	}

	if (isAfternoon)
	{
		result = HOURS_PER_DAY - result;
	}
	return result;
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
	if (time > HOURS_PER_HALF_DAY)
	{
		time = HOURS_PER_DAY - time;
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
		time += HOURS_PER_DAY;
	}
	while (time >= HOURS_PER_DAY)
	{
		time -= HOURS_PER_DAY;
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

static bool IsInsideCitadel()
{
	if (LH3DLevelOfDetail::g_b_inside_citadel != 0 && !LH3DTexture::g_b_use_low_res)
	{
		return true;
	}
	return false;
}

void LH3DSky::Draw()
{
	LHPoint moonPosition = LH3DAtmos::moonpos;

	int moonAlpha = (int)(moonPosition.y * LH3D_SKY_MOON_FOG_SCALE - LH3D_SKY_MOON_FOG_OFFSET);
	if (moonAlpha > LH3D_SKY_MOON_FOG_MAX)
	{
		moonAlpha = LH3D_SKY_MOON_FOG_MAX;
	}
	if (overcast > 0.0f && LH3DIsland::g_b_use_fog)
	{
		moonAlpha = (int)((float)moonAlpha / (overcast * LH3D_SKY_FOG_SCALE + 1.0f));
	}

	uint32_t specular = 0;
	if (moonAlpha > 0)
	{
		moonPosition.x += LH3DTech::g_camera.pos.x;
		moonPosition.y += LH3DTech::g_camera.pos.y;
		moonPosition.z += LH3DTech::g_camera.pos.z;
		moonobj->SetNeedClipping(1);
	}

	int alignmentAlpha;
	int alignmentIndex;
	int nextAlignmentIndex;
	if (evil < 0.0f)
	{
		evil = 0.0f;
		alignmentAlpha = (int)(evil * LH3D_SKY_ALPHA_MAX);
		alignmentIndex = 0;
		nextAlignmentIndex = 1;
	}
	else
	{
		if (evil > 2.0f)
		{
			evil = 2.0f;
		}
		alignmentAlpha = (int)((evil - 1.0f) * LH3D_SKY_ALPHA_MAX);
		alignmentIndex = 1;
		nextAlignmentIndex = 2;
	}

	int inverseAlignmentAlpha = 0xff - alignmentAlpha;

	LH3DRender::SetRenderState(D3DRENDERSTATE_ZFUNC, D3DCMP_ALWAYS);

	int      fogAlpha = (int)(overcast * LH3D_SKY_ALPHA_MAX);
	uint32_t topColour = 0xffffffff;
	if (!IsInsideCitadel())
	{
		float skyBrightness = (2.0f - newst) * LH3D_SKY_TOP_SCALE;
		float redScale = skyBrightness + skyBrightness + LH3D_SKY_TOP_OFFSET;
		float greenScale = skyBrightness * LH3D_SKY_TOP_GREEN_SCALE + LH3D_SKY_TOP_OFFSET;
		float blueScale = skyBrightness * LH3D_SKY_TOP_BLUE_SCALE + LH3D_SKY_TOP_OFFSET;
		if (redScale > 1.0f)
		{
			redScale = 1.0f;
		}
		if (greenScale > 1.0f)
		{
			greenScale = 1.0f;
		}
		if (blueScale > 1.0f)
		{
			blueScale = 1.0f;
		}

		LH3DColor colour = topcol;
		colour.r = (uint8_t)((float)colour.r * redScale);
		colour.g = (uint8_t)((float)colour.g * greenScale);
		colour.b = (uint8_t)((float)colour.b * blueScale);
		colour.a = 0xff;
		topColour = colour.GetColor();
	}

	uint32_t fogColour =
		((uint32_t)(uint8_t)fog_red << 16) | ((uint32_t)(uint8_t)fog_green << 8) | (uint8_t)fog_blue | 0xff000000;

	if (LH3DIsland::g_b_use_fog)
	{
		topColour = LH3D_BLEND_COLOR(topColour, fogColour, fogAlpha);
		specular = LH3D_BLEND_COLOR(0, fogColour, fogAlpha);
	}

	if (LH3DAtmos::alignment & 1)
	{
		int alignmentFade = (LH3DAtmos::fade * LH3DAtmos::fade) / LH3D_ATMOS_ALIGNMENT_FADE;
		topColour = LH3D_BLEND_COLOR(0, topColour, 0xff - alignmentFade);
		specular = LH3D_BLEND_COLOR(0, specular, 0xff - alignmentFade);
	}

	if (g_fade != 0)
	{
		topColour = LH3D_BLEND_COLOR(topColour, 0xffffffff, g_fade);
		specular = LH3D_BLEND_COLOR(specular, 0xffffffff, g_fade / 2);
	}

	if (inverseAlignmentAlpha < 1)
	{
		DrawSky(nextAlignmentIndex, 0xff, topColour, specular);
	}
	else
	{
		DrawSky(alignmentIndex, 0xff, topColour, specular);
		if (alignmentAlpha > 0)
		{
			DrawSky(nextAlignmentIndex, alignmentAlpha, topColour, specular);
		}
	}

	LH3DRender::SetRenderState(D3DRENDERSTATE_ZFUNC, D3DCMP_LESSEQUAL);

	DrawSun();

	if (moonAlpha > 0)
	{
		LH3DColor moonColour = lightcols[5];
		moonColour.a = (uint8_t)moonAlpha;
		moonflip = false;
		LHMatrix quadMatrix;
		LHMatrix moonMatrix;
		CalcMoonMat(moonPosition, quadMatrix, moonMatrix);
		DrawMoonPost(moonColour, quadMatrix, moonMatrix);
		moonPosition.y = -moonPosition.y;
		moonflip = true;
		CalcMoonMat(moonPosition, quadMatrix, moonMatrix);
		DrawMoonPost(moonColour, quadMatrix, moonMatrix);
	}
}

void LH3DSky::Init(float alignment, float time)
{
	SetDayNightTimes(LH3D_SKY_DEFAULT_NIGHT, LH3D_SKY_DEFAULT_DUSK, LH3D_SKY_DEFAULT_DUSK_END, LH3D_SKY_DEFAULT_DAY);
	g_jc_caca_first_init_sky = true;
	moonsize = LH3D_SKY_MOON_SIZE_DEFAULT;
	moonsize = LH3D_SKY_MOON_SIZE;
	memset(bitmaps, 0, sizeof(bitmaps));

	int skyTypeCount = IsInsideCitadel() ? SKY_DETAIL_COUNT : SKY_DETAIL_COUNT_DAY;
	for (int skyType = 0; skyType < skyTypeCount; skyType++)
	{
		for (int alignmentIndex = 0; alignmentIndex < SKY_TYPE_COUNT; alignmentIndex++)
		{
			strcpy(g_sky_texture_name, "Data\\WeatherSystem\\sky_");
			if (alignmentIndex == 0)
			{
				strcat(g_sky_texture_name, "good");
			}
			else if (alignmentIndex == 1)
			{
				strcat(g_sky_texture_name, "ntrl");
			}
			else
			{
				strcat(g_sky_texture_name, "evil");
			}
			if (skyType == SKY_TYPE_DAY)
			{
				strcat(g_sky_texture_name, "_day.555");
			}
			else if (skyType == SKY_TYPE_DUSK)
			{
				strcat(g_sky_texture_name, "_dusk.555");
			}
			else
			{
				strcat(g_sky_texture_name, "_night.555");
			}
			bitmaps[skyType][alignmentIndex] = LoadTextureCitadel(g_sky_texture_name, NULL);
		}
		if (bitmaps[skyType][0] == NULL)
		{
			bitmaps[skyType][0] = bitmaps[skyType][1];
		}
		if (bitmaps[skyType][2] == NULL)
		{
			bitmaps[skyType][2] = bitmaps[skyType][1];
		}
	}

	int index;
	for (index = 0; index < SKY_DETAIL_COUNT; index++)
	{
		TextureFormat format;
		sky_texture[index] = LH3DTexture::Create(NULL, LH3D_SKY_TEXTURE_SIZE, 0, &format);
		sky_material[index] =
			LH3DRender::CreateMaterial(LH3DMaterial::LH3D_MATERIAL_RENDER_MODE_TEXTURED, sky_texture[index]);
	}

	int textureHeight = LH3DTexture::g_b_use_low_res ? SKY_TEXTURE_HEIGHT_LOW : SKY_TEXTURE_HEIGHT;
	CalculateTextures(Time2SkyType(time), 0, textureHeight);
	cury = textureHeight;
	newst = 0.0f;
	evil = alignment * LH3D_SKY_EVIL_SCALE;
	curst = 0.0f;
	SetTime(time);
	LH3DSky::overcast = 0.0f;
	CalculateColours();

	uint32_t fileLength;
	LHFileLength("data\\weathersystem\\sky.l3d", &fileLength);
	void* meshData = LH3DMem::Alloc(fileLength);
	LHLoadData("data\\weathersystem\\sky.l3d", meshData, fileLength, NULL);
	skymesh = LH3DMesh::Create(meshData, false);
	LH3DMem::Free(meshData);

	sky = LH3DObject::Create(LH3DObject::STATIC);
	sky->SetMesh(skymesh, NULL, NULL);
	sky->SetDynamicLighting(false);
	sky->SetPosition(LHPoint(LH3D_SKY_POSITION, 0.0f, LH3D_SKY_POSITION), 0.0f, LH3D_SKY_SCALE);

	int primitiveIndex;
	moon = LH3DMesh::CreateFromHD("Data\\WeatherSystem\\moon.l3d", 1);
	for (index = 0; index < moon->SubmeshCount; index++)
	{
		LH3DSubMesh* submesh = moon->submeshes[index];
		for (primitiveIndex = 0; primitiveIndex < submesh->NumPrimitives; primitiveIndex++)
		{
			LH3DPrimitive* primitive = submesh->primitives_[primitiveIndex];
			primitive->Material.texture = g_weather_texture;
		}
	}

	sun = LH3DMesh::CreateFromHD("Data\\WeatherSystem\\sun.l3d", 1);
	for (index = 0; index < sun->SubmeshCount; index++)
	{
		LH3DSubMesh* submesh = sun->submeshes[index];
		for (primitiveIndex = 0; primitiveIndex < submesh->NumPrimitives; primitiveIndex++)
		{
			LH3DPrimitive* primitive = submesh->primitives_[primitiveIndex];
			primitive->Material.render_mode = LH3DMaterial::LH3D_MATERIAL_RENDER_MODE_ALPHA_TEXTURED_ALPHA_ADDITIF_NZ;
			primitive->Material.Flags = primitive->Material.Flags | LH3DMaterial::FLAG_DOUBLE_SIDED;
			primitive->Material.texture = g_sun_texture;
		}
	}

	moonobj = LH3DObject::Create(LH3DObject::STATIC);
	moonobj->SetMesh(moon, NULL, NULL);
	moonobj->SetDynamicLighting(false);

	sunobj = LH3DObject::Create(LH3DObject::STATIC);
	sunobj->SetMesh(sun, NULL, NULL);
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

	LH3DAtmos::v_pnt[0][0].x = quad_matrix.m[9] - (quad_matrix.m[3] + quad_matrix.m[0]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][0].y = quad_matrix.m[10] - (quad_matrix.m[4] + quad_matrix.m[1]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][0].z = quad_matrix.m[11] - (quad_matrix.m[5] + quad_matrix.m[2]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][1].x = quad_matrix.m[9] + (quad_matrix.m[0] - quad_matrix.m[3]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][1].y = quad_matrix.m[10] + (quad_matrix.m[1] - quad_matrix.m[4]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][1].z = quad_matrix.m[11] + (quad_matrix.m[2] - quad_matrix.m[5]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][2].x = quad_matrix.m[9] + (quad_matrix.m[3] - quad_matrix.m[0]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][2].y = quad_matrix.m[10] + (quad_matrix.m[4] - quad_matrix.m[1]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][2].z = quad_matrix.m[11] + (quad_matrix.m[5] - quad_matrix.m[2]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][3].x = quad_matrix.m[9] + (quad_matrix.m[3] + quad_matrix.m[0]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][3].y = quad_matrix.m[10] + (quad_matrix.m[4] + quad_matrix.m[1]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][3].z = quad_matrix.m[11] + (quad_matrix.m[5] + quad_matrix.m[2]) * LH3D_SKY_MOON_QUAD_SIZE;

	LH3DTech::Draw3DWorldTriangle(LH3D_SKY_MOON_VERTEX_COUNT, LH3DAtmos::v_pnt[0], LH3DAtmos::v_col[0],
	                              LH3DAtmos::v_uv[0], LH3D_SKY_MOON_TRIANGLE_COUNT, LH3DAtmos::v_idx[0],
	                              LH3DAtmos::AdditiveMaterial, 0);

	moonobj->matrix = moon_matrix;
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

float LH3DSky::GetSunVisibility()
{
	static float sampleOffset = LH3D_SKY_SUN_SAMPLE_OFFSET;
	LHPoint      samplePositions[] = {
		LHPoint(0.0f, 0.0f, 0.0f),                   //
		LHPoint(-sampleOffset, -sampleOffset, 0.0f), //
		LHPoint(-sampleOffset, sampleOffset, 0.0f),  //
		LHPoint(sampleOffset, -sampleOffset, 0.0f),  //
		LHPoint(sampleOffset, sampleOffset, 0.0f),   //
	};
	LHPoint direction = g_sun_pos;
	direction -= LH3DTech::g_camera.pos;
	direction.SetSize(LH3DTech::g_info_transform.NearClip);

	HRESULT        lockResult = S_FALSE;
	bool32_t       readDepth = g_b_zbuffer_16b;
	DDSURFACEDESC2 depthSurface;
	if (LH3DLevelOfDetail::g_detail_idx != LH3DLevelOfDetail::DETAIL_PRESET_3 &&
	    LH3DLevelOfDetail::g_detail_idx != LH3DLevelOfDetail::DETAIL_PRESET_4 &&
	    LH3DLevelOfDetail::g_detail_idx != LH3DLevelOfDetail::DETAIL_PRESET_6)
	{
		readDepth = false;
	}
	if (readDepth)
	{
		memset(&depthSurface, 0, sizeof(depthSurface));
		depthSurface.dwSize = sizeof(depthSurface);
		lockResult = LH3DRender::ZBufferSurface->Lock(NULL, &depthSurface,
		                                              DDLOCK_WAIT | DDLOCK_READONLY | DDLOCK_NOSYSLOCK, NULL);
	}

	float occludedSamples = 0.0f;
	for (int sampleIndex = 0; sampleIndex < ARRAY_SIZE(samplePositions); ++sampleIndex)
	{
		samplePositions[sampleIndex] += g_sun_pos;
		samplePositions[sampleIndex] += direction;
		if (samplePositions[sampleIndex].y < LH3D_SKY_SUN_MIN_HEIGHT)
		{
			samplePositions[sampleIndex].y = LH3D_SKY_SUN_MIN_HEIGHT;
		}
		float    hitX, hitZ;
		bool32_t occluded = LH3DIsland::RayCast(LH3DTech::g_camera.pos, samplePositions[sampleIndex], &hitX, &hitZ);
		if (!occluded && lockResult == DD_OK && readDepth)
		{
			int screenX, screenY;
			if (LH3DTech::ProjectPoint(&samplePositions[sampleIndex], &screenX, &screenY) ==
			    LH3DTech::PROJECT_POINT_INSIDE_VIEWPORT)
			{
				if (screenX < 0)
				{
					screenX = 0;
				}
				if (screenY < 0)
				{
					screenY = 0;
				}
				if (screenX >= depthSurface.dwWidth)
				{
					screenX = depthSurface.dwWidth - 1;
				}
				if (screenY >= depthSurface.dwHeight)
				{
					screenY = depthSurface.dwHeight - 1;
				}
				uint16_t* depthPixels = (uint16_t*)depthSurface.lpSurface;
				if (depthPixels[screenX + depthSurface.lPitch * screenY / (int)sizeof(*depthPixels)] <
				    LH3D_SKY_SUN_DEPTH_THRESHOLD)
				{
					occluded = true;
				}
			}
		}
		occludedSamples += (occluded != false);
	}
	if (readDepth && lockResult == DD_OK)
	{
		LH3DRender::ZBufferSurface->Unlock(NULL);
	}
	return (1.0f - occludedSamples * LH3D_SKY_SUN_SAMPLE_WEIGHT) * LH3D_SKY_ALPHA_MAX;
}
