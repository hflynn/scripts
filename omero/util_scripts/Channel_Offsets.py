#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
 components/tools/OmeroPy/scripts/omero/util_scripts/Channel_Offsets.py

-----------------------------------------------------------------------------
  Copyright (C) 2006-2014 University of Dundee. All rights reserved.


  This program is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 2 of the License, or
  (at your option) any later version.
  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License along
  with this program; if not, write to the Free Software Foundation, Inc.,
  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

------------------------------------------------------------------------------

This script creates new images from existing images, applying x, y, and z
shifts to each channel independently, as specified in the parameters.

@author  Will Moore &nbsp;&nbsp;&nbsp;&nbsp;
<a href="mailto:will@lifesci.dundee.ac.uk">will@lifesci.dundee.ac.uk</a>
@version 3.0
<small>
(<b>Internal version:</b> $Revision: $Date: $)
</small>
@since 3.0-Beta4.3

"""

import omero
from omero.gateway import BlitzGateway
import omero.scripts as scripts
from omero.rtypes import rlong, rstring, robject
import omero.util.script_utils as script_utils

from numpy import zeros, hstack, vstack


def newImageWithChannelOffsets(conn, imageId, channel_offsets, dataset=None):
    """
    Process a single image here: creating a new image and passing planes from
    original image to new image - applying offsets to each channel as we go.

    @param imageId:             Original image
    @param channel_offsets:     List of map for each channel {'index':index,
                                'x':x, 'y'y, 'z':z}
    """

    oldImage = conn.getObject("Image", imageId)
    if oldImage is None:
        print "Image not found for ID:", imageId
        return

    if dataset is None:
        dataset = oldImage.getParent()

    # these dimensions don't change
    sizeZ = oldImage.getSizeZ()
    sizeC = oldImage.getSizeC()
    sizeT = oldImage.getSizeT()
    sizeX = oldImage.getSizeX()
    sizeY = oldImage.getSizeY()

    # check we're not dealing with Big image.
    rps = oldImage.getPrimaryPixels()._prepareRawPixelsStore()
    bigImage = rps.requiresPixelsPyramid()
    rps.close()
    if bigImage:
        print "This script does not support 'BIG' images such as Image ID: " \
            "%s X: %d Y: %d" % (imageId, sizeX, sizeY)
        return

    # setup the (z,c,t) list of planes we need
    zctList = []
    for z in range(sizeZ):
        for offset in channel_offsets:
            if offset['index'] < sizeC:
                for t in range(sizeT):
                    zOffset = offset['z']
                    zctList.append((z-zOffset, offset['index'], t))

    print "zctList", zctList

    # for convenience, make a map of channel:offsets
    offsetMap = {}
    channelList = []
    for c in channel_offsets:
        cIndex = c['index']
        if cIndex < sizeC:
            channelList.append(cIndex)
            offsetMap[cIndex] = {'x': c['x'], 'y': c['y'], 'z': c['z']}

    def offsetPlane(plane, x, y):
        """
        Takes a numpy 2D array and returns the same plane offset by x and y,
        adding rows and columns of 0 values
        """
        height, width = plane.shape
        dataType = plane.dtype
        # shift x by cropping, creating a new array of columns and stacking
        # horizontally
        if abs(x) > 0:
            newCols = zeros((height, abs(x)), dataType)
            x1 = max(0, 0-x)
            x2 = min(width, width-x)
            crop = plane[0:height, x1:x2]
            if x > 0:
                plane = hstack((newCols, crop))
            else:
                plane = hstack((crop, newCols))
        # shift y by cropping, creating a new array of rows and stacking
        # vertically
        if abs(y) > 0:
            newRows = zeros((abs(y), width), dataType)
            y1 = max(0, 0-y)
            y2 = min(height, height-y)
            crop = plane[y1:y2, 0:width]
            if y > 0:
                plane = vstack((newRows, crop))
            else:
                plane = vstack((crop, newRows))
        return plane

    def offsetPlaneGen():
        pixels = oldImage.getPrimaryPixels()
        dt = None
        # get the planes one at a time - exceptions on getPlane() don't affect
        # subsequent calls (new RawPixelsStore)
        for i in range(len(zctList)):
            z, c, t = zctList[i]
            offsets = offsetMap[c]
            if z < 0 or z >= sizeZ:
                print "Black plane for zct:", zctList[i]
                if dt is None:
                    # if we are on our first plane, we don't know datatype
                    # yet...
                    dt = pixels.getPlane(0, 0, 0).dtype
                    # hack! TODO: add method to pixels to supply dtype
                plane = zeros((sizeY, sizeX), dt)
            else:
                print "getPlane for zct:", zctList[i], "applying offsets:", \
                    offsets
                try:
                    plane = pixels.getPlane(*zctList[i])
                    dt = plane.dtype
                except:
                    # E.g. the Z-index is out of range - Simply supply an
                    # array of zeros.
                    if dt is None:
                        # if we are on our first plane, we don't know datatype
                        # yet...
                        dt = pixels.getPlane(0, 0, 0).dtype
                        # hack! TODO: add method to pixels to supply dtype
                    plane = zeros((sizeY, sizeX), dt)
            yield offsetPlane(plane, offsets['x'], offsets['y'])

    # create a new image with our generator of numpy planes.
    newImageName = "%s_offsets" % oldImage.getName()
    descLines = [" Channel %s: Offsets x: %s y: %s z: %s" % (c['index'],
                 c['x'], c['y'], c['z']) for c in channel_offsets]
    desc = "Image created from Image ID: %s by applying Channel Offsets:\n" \
        % imageId
    desc += "\n".join(descLines)
    i = conn.createImageFromNumpySeq(
        offsetPlaneGen(), newImageName,
        sizeZ=sizeZ, sizeC=len(offsetMap.items()), sizeT=sizeT,
        description=desc, sourceImageId=imageId, channelList=channelList)

    # Link image to dataset
    link = None
    if dataset and dataset.canLink():
        link = omero.model.DatasetImageLinkI()
        link.parent = omero.model.DatasetI(dataset.getId(), False)
        link.child = omero.model.ImageI(i.getId(), False)
        conn.getUpdateService().saveAndReturnObject(link)

    return i, link


def processImages(conn, scriptParams):
    """
    Process the script params to make a list of channel_offsets, then iterate
    through the images creating a new image from each with the specified
    channel offsets
    """

    message = ""

    # Get the images
    images, logMessage = script_utils.getObjects(conn, scriptParams)
    message += logMessage
    if not images:
        return None, None, message
    imageIds = [i.getId() for i in images]

    # Get the channel offsets
    channel_offsets = []
    for i in range(1, 5):
        pName = "Channel_%s" % i
        if scriptParams[pName]:
            index = i-1     # UI channel index is 1-based - we want 0-based
            x = "Channel%s_X_shift" % i in scriptParams and \
                scriptParams["Channel%s_X_shift" % i] or 0
            y = "Channel%s_Y_shift" % i in scriptParams and \
                scriptParams["Channel%s_Y_shift" % i] or 0
            z = "Channel%s_Z_shift" % i in scriptParams and \
                scriptParams["Channel%s_Z_shift" % i] or 0
            channel_offsets.append({'index': index, 'x': x, 'y': y, 'z': z})

    print channel_offsets

    dataset = None
    if "New_Dataset_Name" in scriptParams:
        # create new Dataset...
        newDatasetName = scriptParams["New_Dataset_Name"]
        dataset = omero.gateway.DatasetWrapper(conn,
                                               obj=omero.model.DatasetI())
        dataset.setName(rstring(newDatasetName))
        dataset.save()
        # add to parent Project
        parentDs = images[0].getParent()
        project = parentDs is not None and parentDs.getParent() or None
        if project is not None and project.canLink():
            link = omero.model.ProjectDatasetLinkI()
            link.parent = omero.model.ProjectI(project.getId(), False)
            link.child = omero.model.DatasetI(dataset.getId(), False)
            conn.getUpdateService().saveAndReturnObject(link)

    # need to handle Datasets eventually - Just do images for now
    newImages = []
    links = []
    for iId in imageIds:
        newImg, link = newImageWithChannelOffsets(conn, iId, channel_offsets,
                                                  dataset)
        if newImg is not None:
            newImages.append(newImg)
            if link is not None:
                links.append(link)

    if not newImages:
        message += "No image created."
    else:
        if len(newImages) == 1:
            if not link:
                linkMessage = " but could not be attached"
            else:
                linkMessage = ""
            message += "New image created%s: %s." % (linkMessage,
                                                     newImages[0].getName())
        elif len(newImages) > 1:
            message += "%s new images created" % len(newImages)
            if not len(links) == len(newImages):
                message += " but some of them could not be attached."
            else:
                message += "."

    return newImages, dataset, message


def runAsScript():

    dataTypes = [rstring('Image')]

    client = scripts.client(
        'Channel_Offsets.py',
        """Create new Images from existing images, applying an x, y and z \
shift to each channel independently.
See http://www.openmicroscopy.org/site/support/omero4/users/\
client-tutorials/insight/insight-util-scripts.html""",

        scripts.String(
            "Data_Type", optional=False, grouping="1",
            description="Pick Images by 'Image' ID or by the ID of their "
            "Dataset'", values=dataTypes, default="Image"),

        scripts.List(
            "IDs", optional=False, grouping="2",
            description="List of Dataset IDs or Image IDs to "
            "process.").ofType(rlong(0)),

        scripts.String(
            "New_Dataset_Name", grouping="3",
            description="If you want the new image(s) in a new Dataset, "
            "put name here"),

        scripts.Bool(
            "Channel_1", grouping="4", default=True,
            description="Choose to include this channel in the output image"),

        scripts.Int(
            "Channel1_X_shift", grouping="4.1", default=0,
            description="Number of pixels to shift this channel in the X "
            "direction. (negative to shift left)"),

        scripts.Int(
            "Channel1_Y_shift", grouping="4.2", default=0,
            description="Number of pixels to shift this channel in the Y"
            " direction. (negative to shift up)"),

        scripts.Int(
            "Channel1_Z_shift", grouping="4.3", default=0,
            description="Offset channel by a number of Z-sections"),

        scripts.Bool(
            "Channel_2", grouping="5", default=True,
            description="Choose to include this channel in the output image"),

        scripts.Int(
            "Channel2_X_shift", grouping="5.1", default=0,
            description="Number of pixels to shift this channel in the X "
            "direction. (negative to shift left)"),

        scripts.Int(
            "Channel2_Y_shift", grouping="5.2", default=0,
            description="Number of pixels to shift this channel in the Y "
            "direction. (negative to shift up)"),

        scripts.Int(
            "Channel2_Z_shift", grouping="5.3", default=0,
            description="Offset channel by a number of Z-sections"),

        scripts.Bool(
            "Channel_3", grouping="6", default=True,
            description="Choose to include this channel in the output image"),

        scripts.Int(
            "Channel3_X_shift", grouping="6.1", default=0,
            description="Number of pixels to shift this channel in the X "
            "direction. (negative to shift left)"),

        scripts.Int(
            "Channel3_Y_shift", grouping="6.2", default=0,
            description="Number of pixels to shift this channel in the Y "
            "direction. (negative to shift up)"),

        scripts.Int(
            "Channel3_Z_shift", grouping="6.3", default=0,
            description="Offset channel by a number of Z-sections"),

        scripts.Bool(
            "Channel_4", grouping="7", default=True,
            description="Choose to include this channel in the output image"),

        scripts.Int(
            "Channel4_X_shift", grouping="7.1", default=0,
            description="Number of pixels to shift this channel in the X "
            "direction. (negative to shift left)"),

        scripts.Int(
            "Channel4_Y_shift", grouping="7.2", default=0,
            description="Number of pixels to shift this channel in the Y "
            "direction. (negative to shift up)"),

        scripts.Int(
            "Channel4_Z_shift", grouping="7.3", default=0,
            description="Offset channel by a number of Z-sections"),

        version="4.2.0",
        authors=["William Moore", "OME Team"],
        institutions=["University of Dundee"],
        contact="ome-users@lists.openmicroscopy.org.uk",
    )

    try:
        scriptParams = client.getInputs(unwrap=True)
        print scriptParams

        # wrap client to use the Blitz Gateway
        conn = BlitzGateway(client_obj=client)

        images, dataset, message = processImages(conn, scriptParams)

        # Return message, new image and new dataset (if applicable) to the
        # client
        client.setOutput("Message", rstring(message))
        if len(images) == 1:
            client.setOutput("Image", robject(images[0]._obj))
        if dataset is not None:
            client.setOutput("New Dataset", robject(dataset._obj))

    finally:
        client.closeSession()

if __name__ == "__main__":
    runAsScript()
